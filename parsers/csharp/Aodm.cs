/*
 * AODM 1.2 reference parser — C#.
 *
 * Parses AODM 1.2 XML into the JSON model defined by
 * aodm-core-1.2.schema.json, and applies the semantic rules from
 * VALIDATION-RULES.md that no schema language can express.
 *
 * .NET 6+, base class library only — System.Xml.Linq for parsing and a small
 * hand-rolled JSON writer.
 *
 *   var doc = Aodm.Parse(xml);
 *   doc.ToJson();      // JSON matching the published schema
 *   doc.Validate();    // IReadOnlyList<Issue>
 *   doc.IsValid();     // no MUST-level errors
 *
 * CLI:
 *   dotnet run -- document.xml
 *   dotnet run -- --validate document.xml
 */

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace FucaSpark.Aodm
{
    public class AodmException : Exception
    {
        public AodmException(string message) : base(message) { }
        public AodmException(string message, Exception inner) : base(message, inner) { }
    }

    public sealed class Issue
    {
        public string Rule { get; }
        public string Message { get; }
        public string Where { get; }
        public string Severity { get; }

        private Issue(string rule, string message, string where, string severity)
        {
            Rule = rule; Message = message; Where = where ?? ""; Severity = severity;
        }

        public static Issue Error(string rule, string message, string where = "")
            => new Issue(rule, message, where, "error");

        public static Issue Warning(string rule, string message, string where = "")
            => new Issue(rule, message, where, "warning");

        public override string ToString()
            => $"{Severity.ToUpperInvariant()} {Rule}: {Message}" +
               (string.IsNullOrEmpty(Where) ? "" : $" [{Where}]");
    }

    /// <summary>An ordered JSON object; insertion order is preserved.</summary>
    public sealed class JsonObject : List<KeyValuePair<string, object>>
    {
        public bool Has(string key) => this.Any(kv => kv.Key == key);

        public object Get(string key)
        {
            foreach (var kv in this) if (kv.Key == key) return kv.Value;
            return null;
        }

        public void Set(string key, object value)
        {
            for (int i = 0; i < Count; i++)
            {
                if (this[i].Key == key) { this[i] = new KeyValuePair<string, object>(key, value); return; }
            }
            Add(new KeyValuePair<string, object>(key, value));
        }

        public void SetIf(string key, object value)
        {
            if (value != null && !(value is string s && s.Length == 0)) Set(key, value);
        }

        public void Remove(string key) => RemoveAll(kv => kv.Key == key);
    }

    public sealed class Document
    {
        public JsonObject Model { get; }
        private readonly List<Issue> _parseIssues;

        internal Document(JsonObject model, List<Issue> parseIssues)
        {
            Model = model; _parseIssues = parseIssues;
        }

        public List<JsonObject> Collection(string name)
            => Model.Get(name) as List<JsonObject> ?? new List<JsonObject>();

        public List<JsonObject> Entities      => Collection("entities");
        public List<JsonObject> Relationships => Collection("relationships");
        public List<JsonObject> Facts         => Collection("facts");
        public List<JsonObject> Rules         => Collection("rules");

        public JsonObject ById(string id)
        {
            foreach (var coll in Aodm.Collections.Values)
                foreach (var item in Collection(coll))
                    if ((item.Get("id") as string) == id) return item;
            return null;
        }

        public IReadOnlyList<Issue> Validate()
        {
            var all = new List<Issue>(_parseIssues);
            all.AddRange(Aodm.ValidateModel(Model));
            return all;
        }

        public IReadOnlyList<Issue> Errors()
            => Validate().Where(i => i.Severity == "error").ToList();

        public IReadOnlyList<Issue> Warnings()
            => Validate().Where(i => i.Severity == "warning").ToList();

        public bool IsValid() => Errors().Count == 0;

        public string ToJson(int indent = 2) => Json.Write(Model, indent);

        /// <summary>Serialise back to the AODM XML form.</summary>
        public string ToXml(int indent = 2) => Aodm.ToXml(Model, indent);
    }

    public static class Aodm
    {
        public const string NS = "http://fucaspark.com/aodm/1.2";
        public const string LegacyNS = "http://fucaspark.com/aodm";
        public const string Version = "1.2";

        private static readonly string[] Primitives = { "entity", "relationship", "fact", "rule" };

        internal static readonly Dictionary<string, string> Collections = new Dictionary<string, string>
        {
            ["entity"] = "entities",
            ["relationship"] = "relationships",
            ["fact"] = "facts",
            ["rule"] = "rules",
        };

        private static readonly Regex DigestRe = new Regex(@"^[a-z0-9-]+:[0-9a-fA-F]{32,128}$");
        private static readonly Regex BareHexRe = new Regex(@"^[0-9a-fA-F]{64}$");
        private static readonly Regex TokenRe = new Regex(@"^[a-z0-9]+(-[a-z0-9]+)*$");
        private static readonly Regex DateRe = new Regex(@"^\d{4}-\d{2}-\d{2}$");
        private static readonly Regex DateTimeRe =
            new Regex(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$");

        /* -------------------------------------------------------------- */
        /* Parsing                                                        */
        /* -------------------------------------------------------------- */

        public static Document Parse(string xml)
        {
            if (string.IsNullOrWhiteSpace(xml))
                throw new AodmException("Nothing to parse: empty input.");

            XDocument dom;
            try
            {
                // External entities are not resolved.
                dom = XDocument.Parse(xml, LoadOptions.None);
            }
            catch (Exception e)
            {
                throw new AodmException("Not well-formed XML: " + e.Message, e);
            }

            var all = dom.Descendants().ToList();
            if (dom.Root != null) all.Insert(0, dom.Root);

            bool sawNs = all.Any(e => e.Name.NamespaceName == NS);
            bool sawLegacy = all.Any(e => e.Name.NamespaceName == LegacyNS);
            if (!sawNs)
            {
                if (sawLegacy)
                    throw new AodmException($"This document uses the v1.1 namespace ({LegacyNS}). " +
                                            $"This parser reads AODM 1.2 ({NS}).");
                throw new AodmException($"No AODM 1.2 elements found. Declare xmlns:aodm=\"{NS}\".");
            }

            var issues = new List<Issue>();
            var model = new JsonObject();
            model.Set("aodm_version", Version);
            var counters = new Dictionary<string, int>();

            foreach (var el in all)
            {
                if (el.Name.NamespaceName != NS) continue;
                string kind = el.Name.LocalName;
                if (Array.IndexOf(Primitives, kind) < 0) continue;

                counters.TryGetValue(kind, out int index);
                counters[kind] = index + 1;

                string id = Attr(el, "id");
                string where = Describe(kind, id, index);

                var item = new JsonObject();
                item.SetIf("id", id);
                item.SetIf("polarity", Attr(el, "polarity"));
                item.SetIf("origin", Attr(el, "origin"));
                item.SetIf("hash", Attr(el, "hash"));
                item.SetIf("valid_from", Attr(el, "valid-from"));
                item.SetIf("valid_to", Attr(el, "valid-to"));

                string derived = Attr(el, "derived-from");
                if (derived != null)
                {
                    var refs = derived.Split((char[])null, StringSplitOptions.RemoveEmptyEntries)
                                      .Cast<object>().ToList();
                    item.Set("derived_from", refs);
                }

                ReadAnnotations(el, item, issues, where);

                switch (kind)
                {
                    case "entity":
                    {
                        if (id == null)
                            issues.Add(Issue.Error("XSD", "entity is missing the required id attribute.", where));
                        string type = Attr(el, "type");
                        if (type != null) item.Set("type", type);
                        else issues.Add(Issue.Error("XSD", "entity is missing the required type attribute.", where));
                        item.SetIf("label", Attr(el, "label"));

                        bool hasNested = el.Descendants().Any(d =>
                            d.Name.NamespaceName == NS && Array.IndexOf(Primitives, d.Name.LocalName) >= 0);
                        string body = hasNested ? "" : TextOf(el);
                        if (body.Length > 0) item.Set("content", body);
                        item.Remove("value");
                        break;
                    }
                    case "relationship":
                    {
                        foreach (var a in new[] { "type", "subject", "predicate", "object" })
                        {
                            string v = Attr(el, a);
                            if (v != null) item.Set(a, v);
                            else issues.Add(Issue.Error("XSD",
                                $"relationship is missing the required {a} attribute.", where));
                        }
                        item.Remove("value");
                        break;
                    }
                    case "fact":
                    {
                        item.SetIf("about", Attr(el, "about"));
                        string asserted = Attr(el, "asserted");
                        if (asserted == "false" || asserted == "0") item.Set("asserted", false);
                        item.Set("statement", TextOf(el));
                        break;
                    }
                    case "rule":
                    {
                        var conds = new List<object>();
                        foreach (var c in el.Elements())
                        {
                            if (c.Name.NamespaceName != NS || c.Name.LocalName != "condition") continue;
                            string cref = Attr(c, "ref");
                            if (cref == null)
                            {
                                issues.Add(Issue.Error("XSD", "rule has a condition with no ref attribute.", where));
                                continue;
                            }
                            var cond = new JsonObject();
                            cond.Set("ref", cref);
                            cond.SetIf("polarity", Attr(c, "polarity"));
                            conds.Add(cond);
                        }
                        if (conds.Count == 0)
                            issues.Add(Issue.Error("XSD", "rule has no conditions; at least one is required.", where));
                        item.Set("conditions", conds);

                        var concl = el.Elements()
                            .Where(c => c.Name.NamespaceName == NS && c.Name.LocalName == "conclusion")
                            .ToList();
                        if (concl.Count == 0)
                        {
                            issues.Add(Issue.Error("XSD", "rule has no conclusion; exactly one is required.", where));
                        }
                        else
                        {
                            if (concl.Count > 1)
                                issues.Add(Issue.Error("XSD",
                                    $"rule has {concl.Count} conclusions; exactly one is allowed.", where));
                            item.SetIf("conclusion", Attr(concl[0], "ref"));
                        }
                        item.Remove("value");
                        break;
                    }
                }

                string collName = Collections[kind];
                if (!(model.Get(collName) is List<JsonObject> list))
                {
                    list = new List<JsonObject>();
                    model.Set(collName, list);
                }
                list.Add(item);
            }

            return new Document(model, issues);
        }

        public static Document ParseFile(string path) => Parse(File.ReadAllText(path));

        /* -------------------------------------------------------------- */
        /* XML helpers                                                    */
        /* -------------------------------------------------------------- */

        private static string Attr(XElement el, string name)
        {
            var a = el.Attribute(name);
            return string.IsNullOrEmpty(a?.Value) ? null : a.Value;
        }

        /// <summary>Text of an element, excluding nested AODM primitives.</summary>
        internal const string HashAlgorithm = "sha256";

        public static string ContentHash(string text)
        {
            using (var sha = System.Security.Cryptography.SHA256.Create())
            {
                var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(text.Trim()));
                var sb = new StringBuilder(HashAlgorithm).Append(':');
                foreach (var b in bytes) sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }

        private static string TextOf(XNode node)
        {
            var sb = new StringBuilder();
            if (node is XElement el)
            {
                foreach (var child in el.Nodes())
                {
                    if (child is XText t) sb.Append(t.Value);
                    else if (child is XElement ce)
                    {
                        // Nested AODM elements are excluded.
                        if (ce.Name.NamespaceName == NS) continue;
                        sb.Append(TextOf(ce));
                    }
                }
            }
            return sb.ToString().Trim();
        }

        /// <summary>All text inside an element; annotations keep their own content.</summary>
        private static string AllText(XElement el)
            => Regex.Replace(string.Concat(el.DescendantNodes().OfType<XText>()
                                             .Select(t => t.Value)), @"\s+", " ").Trim();

        private static object Num(string v)
        {
            if (string.IsNullOrEmpty(v)) return null;
            if (double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out double d))
                return d == Math.Truncate(d) ? (object)(long)d : d;
            return v;
        }

        private static void ReadAnnotations(XElement el, JsonObject item, List<Issue> issues, string where)
        {
            int seenConf = 0, seenVal = 0;
            foreach (var c in el.Elements())
            {
                if (c.Name.NamespaceName != NS) continue;
                switch (c.Name.LocalName)
                {
                    case "confidence":
                        seenConf++;
                        if (!item.Has("confidence"))
                        {
                            item.Set("confidence", Num(Attr(c, "value")));
                            item.SetIf("confidence_method", Attr(c, "method"));
                        }
                        break;
                    case "value":
                        seenVal++;
                        if (!item.Has("value"))
                        {
                            var v = new JsonObject();
                            foreach (var a in new[] { "number", "min", "max", "tolerance" })
                            {
                                var n = Num(Attr(c, a));
                                if (n != null) v.Set(a, n);
                            }
                            v.SetIf("unit", Attr(c, "unit"));
                            if (v.Count > 0) item.Set("value", v);
                        }
                        break;
                    case "evidence":
                    {
                        var ev = new JsonObject();
                        foreach (var a in new[] { "uri", "locator", "retrieved" })
                            ev.SetIf(a, Attr(c, a));
                        string ex = AllText(c);
                        if (ex.Length > 0) ev.Set("excerpt", ex);
                        if (ev.Count > 0)
                        {
                            if (!(item.Get("evidence") is List<object> list))
                            {
                                list = new List<object>();
                                item.Set("evidence", list);
                            }
                            list.Add(ev);
                        }
                        break;
                    }
                    case "source":
                        if (!item.Has("source"))
                        {
                            var s = new JsonObject();
                            foreach (var a in new[] { "uri", "title", "retrieved", "asserted" })
                                s.SetIf(a, Attr(c, a));
                            string t = AllText(c);
                            if (t.Length > 0 && !s.Has("title")) s.Set("title", t);
                            if (s.Count > 0) item.Set("source", s);
                        }
                        break;
                }
            }
            if (seenConf > 1)
                issues.Add(Issue.Error("C1",
                    $"Carries {seenConf} confidence elements; at most one is allowed.", where));
            if (seenVal > 1)
                issues.Add(Issue.Error("C2",
                    $"Carries {seenVal} value elements; at most one is allowed.", where));
        }

        private static string Describe(string kind, string id, int index)
            => id != null ? $"{kind} \"{id}\"" : $"{kind} #{index + 1}";

        /* -------------------------------------------------------------- */
        /* Serialisation back to XML                                      */
        /* -------------------------------------------------------------- */

        private static readonly Dictionary<string, (string, string)[]> AttrOrder =
            new Dictionary<string, (string, string)[]>
            {
                ["entity"] = new[] { ("id","id"),("type","type"),("label","label"),("hash","hash"),
                                     ("polarity","polarity"),("valid_from","valid-from"),
                                     ("valid_to","valid-to"),("derived_from","derived-from") },
                ["relationship"] = new[] { ("id","id"),("type","type"),("subject","subject"),
                                           ("predicate","predicate"),("object","object"),
                                           ("polarity","polarity"),("valid_from","valid-from"),
                                           ("valid_to","valid-to"),("derived_from","derived-from") },
                ["fact"] = new[] { ("id","id"),("about","about"),("asserted","asserted"),
                                   ("origin","origin"),("polarity","polarity"),
                                   ("hash","hash"),("valid_from","valid-from"),
                                   ("valid_to","valid-to"),("derived_from","derived-from") },
                ["rule"] = new[] { ("id","id"),("origin","origin"),("valid_from","valid-from"),("valid_to","valid-to") },
            };

        private static string EscAttr(object v)
            => v.ToString().Replace("&", "&amp;").Replace("<", "&lt;")
                           .Replace(">", "&gt;").Replace("\"", "&quot;");

        private static string EscText(object v)
            => v.ToString().Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;");

        private static string FmtNum(object v)
        {
            double? d = AsDouble(v);
            if (d == null) return v.ToString();
            return d == Math.Truncate(d.Value)
                ? ((long)d.Value).ToString(CultureInfo.InvariantCulture)
                : d.Value.ToString("R", CultureInfo.InvariantCulture);
        }

        public static string ToXml(JsonObject model, int indent = 2)
        {
            string p1 = new string(' ', indent), p2 = p1 + p1;
            var outLines = new List<string>
            {
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
                "<aodm:knowledge version=\"" + EscAttr(model.Get("aodm_version") ?? Version)
                    + "\" xmlns:aodm=\"" + NS + "\">"
            };

            foreach (var pair in Collections)
            {
                string kind = pair.Key;
                var list = model.Get(pair.Value) as List<JsonObject> ?? new List<JsonObject>();

                foreach (var item in list)
                {
                    var attrs = new StringBuilder();
                    foreach (var (key, xmlName) in AttrOrder[kind])
                    {
                        object v = item.Get(key);
                        if (v == null || (v is string vs && vs.Length == 0)) continue;
                        if (v is bool bv) { v = bv ? "true" : "false"; }
                        else if (key == "derived_from")
                        {
                            var refs = (v as List<object>) ?? new List<object>();
                            if (refs.Count == 0) continue;
                            v = string.Join(" ", refs.Select(r => r.ToString()));
                        }
                        attrs.Append(' ').Append(xmlName).Append("=\"").Append(EscAttr(v)).Append('"');
                    }

                    var body = new List<string>();
                    object text = kind == "fact" ? item.Get("statement") : item.Get("content");
                    if (text != null && text.ToString().Length > 0) body.Add(p2 + EscText(text));

                    if (kind == "rule")
                    {
                        foreach (var c in item.Get("conditions") as List<object> ?? new List<object>())
                        {
                            string cref, pol = null;
                            if (c is JsonObject cm)
                            {
                                cref = cm.Get("ref") as string;
                                pol = cm.Get("polarity") as string;
                            }
                            else cref = c as string;
                            body.Add(p2 + "<aodm:condition ref=\"" + EscAttr(cref) + "\""
                                   + (pol != null ? " polarity=\"" + EscAttr(pol) + "\"" : "") + "/>");
                        }
                        if (item.Get("conclusion") is string concl && concl.Length > 0)
                            body.Add(p2 + "<aodm:conclusion ref=\"" + EscAttr(concl) + "\"/>");
                    }

                    if (item.Get("value") is JsonObject val)
                    {
                        var a = new StringBuilder();
                        foreach (var k in new[] { "number", "min", "max", "tolerance", "unit" })
                        {
                            object v = val.Get(k);
                            if (v == null) continue;
                            a.Append(' ').Append(k).Append("=\"")
                             .Append(EscAttr(k == "unit" ? v : FmtNum(v))).Append('"');
                        }
                        body.Add(p2 + "<aodm:value" + a + "/>");
                    }
                    foreach (var evO in item.Get("evidence") as List<object> ?? new List<object>())
                    {
                        var ev = (JsonObject)evO;
                        var ea = new StringBuilder();
                        foreach (var k in new[] { "uri", "locator", "retrieved" })
                        {
                            object v = ev.Get(k);
                            if (v != null) ea.Append(' ').Append(k).Append("=\"").Append(EscAttr(v)).Append('"');
                        }
                        body.Add(ev.Get("excerpt") != null
                            ? p2 + "<aodm:evidence" + ea + ">" + EscText(ev.Get("excerpt")) + "</aodm:evidence>"
                            : p2 + "<aodm:evidence" + ea + "/>");
                    }
                    if (item.Get("source") is JsonObject src)
                    {
                        var a = new StringBuilder();
                        foreach (var k in new[] { "uri", "title", "retrieved", "asserted" })
                        {
                            object v = src.Get(k);
                            if (v != null) a.Append(' ').Append(k).Append("=\"").Append(EscAttr(v)).Append('"');
                        }
                        body.Add(p2 + "<aodm:source" + a + "/>");
                    }
                    if (item.Get("confidence") != null)
                    {
                        object m = item.Get("confidence_method");
                        body.Add(p2 + "<aodm:confidence value=\"" + EscAttr(FmtNum(item.Get("confidence")))
                               + "\"" + (m != null ? " method=\"" + EscAttr(m) + "\"" : "") + "/>");
                    }

                    if (body.Count == 0)
                        outLines.Add(p1 + "<aodm:" + kind + attrs + "/>");
                    else
                    {
                        outLines.Add(p1 + "<aodm:" + kind + attrs + ">");
                        outLines.AddRange(body);
                        outLines.Add(p1 + "</aodm:" + kind + ">");
                    }
                }
            }

            outLines.Add("</aodm:knowledge>");
            return string.Join("\n", outLines);
        }

        /* -------------------------------------------------------------- */
        /* Validation                                                     */
        /* -------------------------------------------------------------- */

        private static bool IsTemporal(string v)
            => v != null && (DateRe.IsMatch(v) || DateTimeRe.IsMatch(v));

        private static DateTimeOffset? TemporalValue(string v)
        {
            if (!IsTemporal(v)) return null;
            string s = DateRe.IsMatch(v) ? v + "T00:00:00Z" : v;
            return DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var d)
                ? d : (DateTimeOffset?)null;
        }

        private static double? AsDouble(object o)
        {
            if (o == null) return null;
            if (o is long l) return l;
            if (o is double d) return d;
            if (o is int i) return i;
            if (o is string s &&
                double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out double parsed))
                return parsed;
            return null;
        }

        private static string TrimNum(double d)
            => d == Math.Truncate(d)
                ? ((long)d).ToString(CultureInfo.InvariantCulture)
                : d.ToString(CultureInfo.InvariantCulture);

        public static List<Issue> ValidateModel(JsonObject model)
        {
            var issues = new List<Issue>();
            var byId = new Dictionary<string, JsonObject>();
            var kindOf = new Dictionary<string, string>();

            foreach (var pair in Collections)
            {
                var list = model.Get(pair.Value) as List<JsonObject> ?? new List<JsonObject>();
                for (int i = 0; i < list.Count; i++)
                {
                    if (!(list[i].Get("id") is string id) || id.Length == 0) continue;
                    if (byId.ContainsKey(id))
                    {
                        issues.Add(Issue.Error("R5", $"Duplicate id \"{id}\". Ids must be unique across " +
                            "the whole document, regardless of element type.", Describe(pair.Key, id, i)));
                    }
                    else { byId[id] = list[i]; kindOf[id] = pair.Key; }
                }
            }

            var now = DateTimeOffset.UtcNow;

            foreach (var pair in Collections)
            {
                string kind = pair.Key;
                var list = model.Get(pair.Value) as List<JsonObject> ?? new List<JsonObject>();

                for (int i = 0; i < list.Count; i++)
                {
                    var item = list[i];
                    string w = Describe(kind, item.Get("id") as string, i);

                    if (kind == "relationship")
                    {
                        foreach (var side in new[] { "subject", "object" })
                        {
                            if (!(item.Get(side) is string r) || r.Length == 0) continue;
                            if (!byId.ContainsKey(r))
                                issues.Add(Issue.Error("R1",
                                    $"The {side} \"{r}\" does not match any entity id in this document.", w));
                            else if (kindOf[r] != "entity")
                                issues.Add(Issue.Error("R1",
                                    $"The {side} \"{r}\" refers to a {kindOf[r]}, but must refer to an entity.", w));
                        }
                    }

                    if (kind == "fact" && item.Get("about") is string about && about.Length > 0)
                    {
                        if (!byId.ContainsKey(about))
                            issues.Add(Issue.Error("R2",
                                $"about=\"{about}\" does not match any id in this document.", w));
                        else if (kindOf[about] != "entity" && kindOf[about] != "relationship")
                            issues.Add(Issue.Error("R2", $"about=\"{about}\" refers to a {kindOf[about]}; " +
                                "it must refer to an entity or relationship.", w));
                    }

                    if (kind == "rule")
                    {
                        var conds = item.Get("conditions") as List<object> ?? new List<object>();
                        var refs = new List<string>();
                        foreach (var c in conds)
                        {
                            string r = c is JsonObject jo ? jo.Get("ref") as string : c as string;
                            if (r == null) continue;
                            refs.Add(r);
                            if (!byId.ContainsKey(r))
                                issues.Add(Issue.Error("R3",
                                    $"Condition ref=\"{r}\" does not match any id in this document.", w));
                            else if (kindOf[r] != "fact" && kindOf[r] != "entity")
                                issues.Add(Issue.Error("R3", $"Condition ref=\"{r}\" refers to a " +
                                    $"{kindOf[r]}; it must refer to a fact or entity.", w));
                        }
                        if (item.Get("conclusion") is string concl && concl.Length > 0)
                        {
                            if (!byId.ContainsKey(concl))
                                issues.Add(Issue.Error("R3",
                                    $"Conclusion ref=\"{concl}\" does not match any id in this document.", w));
                            if (refs.Contains(concl))
                                issues.Add(Issue.Error("R4", $"This rule lists its own conclusion " +
                                    $"\"{concl}\" as a condition. Self-referential rules are not allowed.", w));
                        }
                    }

                    foreach (var rObj in item.Get("derived_from") as List<object> ?? new List<object>())
                    {
                        string r = rObj as string;
                        if (r == null) continue;
                        if (!byId.ContainsKey(r))
                            issues.Add(Issue.Error("R6", $"derived-from references \"{r}\", which does " +
                                "not match any id in this document.", w));
                        else if (kindOf[r] != "fact" && kindOf[r] != "rule" && kindOf[r] != "entity")
                            issues.Add(Issue.Error("R6", $"derived-from references a {kindOf[r]}; " +
                                "it must reference a fact, rule, or entity.", w));
                    }

                    object confObj = item.Get("confidence");
                    if (confObj != null)
                    {
                        double? conf = AsDouble(confObj);
                        if (conf == null)
                            issues.Add(Issue.Error("V1", "Confidence is not a number.", w));
                        else if (conf < 0.0 || conf > 1.0)
                            issues.Add(Issue.Error("V1",
                                $"Confidence {TrimNum(conf.Value)} is outside the allowed range 0.0-1.0.", w));
                        else if (conf < 0.5 && kind == "fact")
                            issues.Add(Issue.Warning("P2", "Confidence is below 0.5. Consumers should be " +
                                "shown that this fact is uncertain.", w));
                    }

                    if (item.Get("source") is JsonObject src)
                    {
                        foreach (var k in new[] { "retrieved", "asserted" })
                        {
                            if (src.Get(k) is string v && v.Length > 0 && !IsTemporal(v))
                                issues.Add(Issue.Error("V2",
                                    $"source {k}=\"{v}\" is not a valid ISO 8601 date.", w));
                        }
                        string ret = src.Get("retrieved") as string;
                        string ass = src.Get("asserted") as string;
                        if (ret != null && IsTemporal(ret) && TemporalValue(ret) > now)
                            issues.Add(Issue.Error("V2", $"source retrieved=\"{ret}\" is in the future.", w));
                        if (ret != null && ass != null && IsTemporal(ret) && IsTemporal(ass)
                            && TemporalValue(ass) > TemporalValue(ret))
                            issues.Add(Issue.Error("V2", $"source asserted=\"{ass}\" is later than " +
                                $"retrieved=\"{ret}\". A source cannot be written after you fetched it.", w));
                    }

                    if (kind == "entity" && item.Get("type") is string ty && !TokenRe.IsMatch(ty))
                        issues.Add(Issue.Warning("V3",
                            $"type=\"{ty}\" should be a lowercase, hyphen-separated token.", w));
                    if (kind == "relationship" && item.Get("predicate") is string pr && !TokenRe.IsMatch(pr))
                        issues.Add(Issue.Warning("V3",
                            $"predicate=\"{pr}\" should be a lowercase, hyphen-separated token.", w));

                    if (item.Get("value") is JsonObject val)
                    {
                        bool hasNum = val.Get("number") != null;
                        bool hasMin = val.Get("min") != null;
                        bool hasMax = val.Get("max") != null;
                        if (hasNum && (hasMin || hasMax))
                            issues.Add(Issue.Error("M1", "A value must use either number (a point value) " +
                                "or min and max (a range), not both.", w));
                        else if (!hasNum && !(hasMin && hasMax))
                            issues.Add(Issue.Error("M1", (hasMin || hasMax)
                                ? "A range value needs both min and max."
                                : "A value must carry either number, or both min and max.", w));
                        if (hasMin && hasMax)
                        {
                            double? mn = AsDouble(val.Get("min")), mx = AsDouble(val.Get("max"));
                            if (mn != null && mx != null && mn > mx)
                                issues.Add(Issue.Error("M2",
                                    $"min ({TrimNum(mn.Value)}) is greater than max ({TrimNum(mx.Value)}).", w));
                        }
                        if (val.Get("tolerance") != null)
                        {
                            double? tol = AsDouble(val.Get("tolerance"));
                            if (tol != null && tol < 0)
                                issues.Add(Issue.Error("M2", "tolerance must not be negative.", w));
                            if (!hasNum)
                                issues.Add(Issue.Error("M2",
                                    "tolerance may only accompany a number, not a min/max range.", w));
                        }
                        if (val.Get("unit") == null && (hasNum || hasMin))
                            issues.Add(Issue.Warning("M3", "This measurement has no unit. Add one (a UCUM " +
                                "code such as Cel, mm, kg, bar) unless the quantity is dimensionless.", w));
                    }

                    foreach (var p in new[] { ("valid_from", "valid-from"), ("valid_to", "valid-to") })
                    {
                        if (item.Get(p.Item1) is string v && v.Length > 0 && !IsTemporal(v))
                            issues.Add(Issue.Error("T1",
                                $"{p.Item2}=\"{v}\" is not a valid ISO 8601 date or date-time.", w));
                    }
                    string vf = item.Get("valid_from") as string, vt = item.Get("valid_to") as string;
                    if (vf != null && vt != null && IsTemporal(vf) && IsTemporal(vt)
                        && TemporalValue(vt) < TemporalValue(vf))
                        issues.Add(Issue.Error("T1",
                            $"valid-to ({vt}) is earlier than valid-from ({vf}).", w));

                    if (item.Get("polarity") is string pol && pol != "positive" && pol != "negative")
                        issues.Add(Issue.Error("N1",
                            $"polarity=\"{pol}\" is not allowed; use \"positive\" or \"negative\".", w));

                    if (item.Get("hash") is string hash && hash.Length > 0)
                    {
                        if (BareHexRe.IsMatch(hash))
                            issues.Add(Issue.Error("H1", "This is a bare hex digest, the v1.1 form. " +
                                $"AODM 1.2 requires a named algorithm: \"sha256:{hash.Substring(0, 12)}...\".", w));
                        else if (!DigestRe.IsMatch(hash))
                            issues.Add(Issue.Error("H1",
                                $"hash=\"{hash}\" is not of the form <algorithm>:<hex-digest>.", w));
                        else
                        {
                            var algorithm = hash.Substring(0, hash.IndexOf(':')).ToLowerInvariant();
                            var body = (kind == "fact" ? item.Get("statement") : item.Get("content")) as string;
                            if (!string.IsNullOrEmpty(body) && algorithm == HashAlgorithm)
                            {
                                var expected = ContentHash(body);
                                if (!string.Equals(expected, hash, StringComparison.OrdinalIgnoreCase))
                                    issues.Add(Issue.Error("H4", $"hash=\"{hash}\" does not match the " +
                                        $"digest of this item's text content ({expected}).", w));
                            }
                        }
                    }

                    if ((item.Get("origin") as string) == "generated")
                    {
                        if (item.Get("confidence") == null)
                            issues.Add(Issue.Error("G3", "origin=\"generated\" marks this a "
                                + "proposal, but it carries no confidence. Nothing states how far "
                                + "it should be trusted.", w));
                        if ((item.Get("evidence") as List<object> ?? new List<object>()).Count == 0)
                            issues.Add(Issue.Warning("G3", "origin=\"generated\" without evidence "
                                + "is unreviewable: nothing shows what prompted the claim.", w));
                    }
                    foreach (var evO in item.Get("evidence") as List<object> ?? new List<object>())
                        if ((evO as JsonObject)?.Get("locator") == null)
                            issues.Add(Issue.Warning("G4", "evidence has no locator, so a reviewer "
                                + "must re-read the whole source to check it.", w));
                    if ((item.Get("origin") as string) == "derived"
                        && (item.Get("derived_from") as List<object> ?? new List<object>()).Count == 0)
                        issues.Add(Issue.Warning("G5", "origin=\"derived\" but nothing named in "
                            + "derived-from; the claim cannot be explained or retracted.", w));

                    if (kind == "fact" && item.Get("asserted") is bool a && !a
                        && (item.Get("source") != null || item.Get("confidence") != null))
                        issues.Add(Issue.Warning("A3", "asserted=\"false\" declares the fact "
                            + "unclaimed, yet it carries a source or confidence. One or the "
                            + "other is wrong.", w));

                    if ((kind == "fact" || kind == "rule")
                        && item.Get("source") == null && item.Get("confidence") == null
                        && !(item.Get("asserted") is bool na && !na)
                        && (item.Get("derived_from") as List<object> ?? new List<object>()).Count == 0)
                        issues.Add(Issue.Warning("P1",
                            "No source and no confidence. Consumers should treat this as unverified.", w));
                }
            }

            // R7 — derivation graph must be acyclic
            var state = new Dictionary<string, int>();
            bool reported = false;

            void Visit(string id, List<string> stack)
            {
                if (state.TryGetValue(id, out int st))
                {
                    if (st == 1) return;
                    if (st == 0)
                    {
                        if (!reported)
                        {
                            var cycle = stack.Skip(stack.IndexOf(id)).ToList();
                            cycle.Add(id);
                            issues.Add(Issue.Error("R7", "Derivation cycle detected: " +
                                string.Join(" -> ", cycle) +
                                ". A fact cannot derive from itself, directly or transitively."));
                            reported = true;
                        }
                        return;
                    }
                }
                state[id] = 0;
                byId.TryGetValue(id, out var node);
                var next = new List<string>(stack) { id };
                foreach (var r in node?.Get("derived_from") as List<object> ?? new List<object>())
                    if (r is string rs) Visit(rs, next);
                if (kindOf.TryGetValue(id, out string k) && k == "rule")
                {
                    foreach (var c in node?.Get("conditions") as List<object> ?? new List<object>())
                    {
                        string r = c is JsonObject jo ? jo.Get("ref") as string : c as string;
                        if (r != null) Visit(r, next);
                    }
                }
                state[id] = 1;
            }

            foreach (var id in byId.Keys.ToList()) Visit(id, new List<string>());

            return issues;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Minimal JSON writer                                                */
    /* ------------------------------------------------------------------ */

    internal static class Json
    {
        public static string Write(object o, int indent)
        {
            var sb = new StringBuilder();
            WriteValue(sb, o, indent, 0);
            return sb.ToString();
        }

        private static void WriteValue(StringBuilder sb, object o, int indent, int depth)
        {
            switch (o)
            {
                case null: sb.Append("null"); return;
                case JsonObject obj:
                {
                    if (obj.Count == 0) { sb.Append("{}"); return; }
                    sb.Append('{');
                    for (int i = 0; i < obj.Count; i++)
                    {
                        if (i > 0) sb.Append(',');
                        NewLine(sb, indent, depth + 1);
                        WriteString(sb, obj[i].Key);
                        sb.Append(':');
                        if (indent > 0) sb.Append(' ');
                        WriteValue(sb, obj[i].Value, indent, depth + 1);
                    }
                    NewLine(sb, indent, depth);
                    sb.Append('}');
                    return;
                }
                case System.Collections.IEnumerable seq when !(o is string):
                {
                    var items = seq.Cast<object>().ToList();
                    if (items.Count == 0) { sb.Append("[]"); return; }
                    sb.Append('[');
                    for (int i = 0; i < items.Count; i++)
                    {
                        if (i > 0) sb.Append(',');
                        NewLine(sb, indent, depth + 1);
                        WriteValue(sb, items[i], indent, depth + 1);
                    }
                    NewLine(sb, indent, depth);
                    sb.Append(']');
                    return;
                }
                case bool b: sb.Append(b ? "true" : "false"); return;
                case long l: sb.Append(l.ToString(CultureInfo.InvariantCulture)); return;
                case int n: sb.Append(n.ToString(CultureInfo.InvariantCulture)); return;
                case double d:
                    sb.Append(d == Math.Truncate(d)
                        ? ((long)d).ToString(CultureInfo.InvariantCulture)
                        : d.ToString("R", CultureInfo.InvariantCulture));
                    return;
                default: WriteString(sb, o.ToString()); return;
            }
        }

        private static void NewLine(StringBuilder sb, int indent, int depth)
        {
            if (indent <= 0) return;
            sb.Append('\n').Append(new string(' ', indent * depth));
        }

        private static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"':  sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }

    /* ------------------------------------------------------------------ */
    /* CLI                                                                */
    /* ------------------------------------------------------------------ */

    public static class Program
    {
        public static int Main(string[] args)
        {
            bool validateOnly = args.Any(a => a == "--validate" || a == "-v");
            string path = args.FirstOrDefault(a => !a.StartsWith("-"));

            if (path == null)
            {
                Console.Error.WriteLine("usage: Aodm [--validate] <file.xml>");
                return 2;
            }

            Document doc;
            try { doc = Aodm.ParseFile(path); }
            catch (AodmException e)
            {
                Console.Error.WriteLine("error: " + e.Message);
                return 1;
            }

            if (args.Contains("--xml"))
            {
                Console.WriteLine(doc.ToXml());
                return doc.Errors().Count > 0 ? 1 : 0;
            }

            var issues = doc.Validate();
            int errors = doc.Errors().Count, warnings = doc.Warnings().Count;

            if (validateOnly)
            {
                foreach (var i in issues)
                {
                    if (i.Severity == "error") Console.Error.WriteLine(i);
                    else Console.WriteLine(i);
                }
                var counts = Aodm.Collections.Values
                    .Select(c => new { c, n = doc.Collection(c).Count })
                    .Where(x => x.n > 0)
                    .Select(x => $"{x.n} {x.c}");
                string summary = counts.Any() ? string.Join(", ", counts) : "empty document";
                Console.WriteLine($"\n{summary} — {errors} error(s), {warnings} warning(s)");
            }
            else
            {
                Console.WriteLine(doc.ToJson());
            }

            return errors > 0 ? 1 : 0;
        }
    }
}
