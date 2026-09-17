/*
 * AODM 1.2 reference parser — Java.
 *
 * Parses AODM 1.2 XML into the JSON model defined by
 * aodm-core-1.2.schema.json, and applies the semantic rules from
 * VALIDATION-RULES.md that no schema language can express.
 *
 * JDK 11+, standard library only — javax.xml for parsing, and a small
 * hand-rolled JSON writer.
 *
 *   Aodm.Document doc = Aodm.parse(xmlString);
 *   doc.toJson();          // JSON matching the published schema
 *   doc.validate();        // List<Issue>
 *   doc.isValid();         // no MUST-level errors
 *
 * CLI:
 *   javac Aodm.java && java Aodm document.xml
 *   java Aodm --validate document.xml
 */

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;

import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

public final class Aodm {

    public static final String NS = "http://fucaspark.com/aodm/1.2";
    public static final String LEGACY_NS = "http://fucaspark.com/aodm";
    public static final String VERSION = "1.2";

    private static final List<String> PRIMITIVES =
            Arrays.asList("entity", "relationship", "fact", "rule");

    private static final Map<String, String> COLLECTION = new LinkedHashMap<>();
    static {
        COLLECTION.put("entity", "entities");
        COLLECTION.put("relationship", "relationships");
        COLLECTION.put("fact", "facts");
        COLLECTION.put("rule", "rules");
    }

    private static final Pattern DIGEST_RE = Pattern.compile("^[a-z0-9-]+:[0-9a-fA-F]{32,128}$");
    private static final Pattern TOKEN_RE = Pattern.compile("^[a-z0-9]+(-[a-z0-9]+)*$");
    private static final Pattern DATE_RE = Pattern.compile("^\\d{4}-\\d{2}-\\d{2}$");
    private static final Pattern DATETIME_RE =
            Pattern.compile("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?$");

    private Aodm() { }

    /** Thrown when input cannot be parsed at all. */
    public static class AodmException extends RuntimeException {
        public AodmException(String m) { super(m); }
        public AodmException(String m, Throwable c) { super(m, c); }
    }

    public static final class Issue {
        public final String rule, message, where, severity;
        Issue(String rule, String message, String where, String severity) {
            this.rule = rule; this.message = message;
            this.where = where == null ? "" : where; this.severity = severity;
        }
        static Issue error(String r, String m, String w)   { return new Issue(r, m, w, "error"); }
        static Issue warning(String r, String m, String w) { return new Issue(r, m, w, "warning"); }
        @Override public String toString() {
            return severity.toUpperCase() + " " + rule + ": " + message
                 + (where.isEmpty() ? "" : " [" + where + "]");
        }
    }

    /** A parsed document: the model, plus issues found while reading it. */
    public static final class Document {
        public final Map<String, Object> model;
        private final List<Issue> parseIssues;

        Document(Map<String, Object> model, List<Issue> parseIssues) {
            this.model = model; this.parseIssues = parseIssues;
        }

        @SuppressWarnings("unchecked")
        public List<Map<String, Object>> collection(String name) {
            Object v = model.get(name);
            return v == null ? new ArrayList<>() : (List<Map<String, Object>>) v;
        }

        public List<Map<String, Object>> entities()      { return collection("entities"); }
        public List<Map<String, Object>> relationships() { return collection("relationships"); }
        public List<Map<String, Object>> facts()         { return collection("facts"); }
        public List<Map<String, Object>> rules()         { return collection("rules"); }

        public Map<String, Object> byId(String id) {
            for (String coll : COLLECTION.values()) {
                for (Map<String, Object> it : collection(coll)) {
                    if (id.equals(it.get("id"))) return it;
                }
            }
            return null;
        }

        public List<Issue> validate() {
            List<Issue> out = new ArrayList<>(parseIssues);
            out.addAll(Aodm.validateModel(model));
            return out;
        }

        public List<Issue> errors() {
            List<Issue> out = new ArrayList<>();
            for (Issue i : validate()) if ("error".equals(i.severity)) out.add(i);
            return out;
        }

        public List<Issue> warnings() {
            List<Issue> out = new ArrayList<>();
            for (Issue i : validate()) if ("warning".equals(i.severity)) out.add(i);
            return out;
        }

        public boolean isValid() { return errors().isEmpty(); }

        public String toJson() { return Json.write(model, 2); }

        /** Serialise back to the AODM XML form. */
        public String toXml() { return Aodm.toXml(model, 2); }
    }

    /* ---------------------------------------------------------------- */
    /* Serialisation back to XML                                        */
    /* ---------------------------------------------------------------- */

    private static final Map<String, String[][]> ATTR_ORDER = new LinkedHashMap<>();
    static {
        ATTR_ORDER.put("entity", new String[][]{
            {"id","id"},{"type","type"},{"label","label"},{"hash","hash"},
            {"polarity","polarity"},{"valid_from","valid-from"},
            {"valid_to","valid-to"},{"derived_from","derived-from"}});
        ATTR_ORDER.put("relationship", new String[][]{
            {"id","id"},{"type","type"},{"subject","subject"},{"predicate","predicate"},
            {"object","object"},{"polarity","polarity"},{"origin","origin"},
            {"valid_from","valid-from"},
            {"valid_to","valid-to"},{"derived_from","derived-from"}});
        ATTR_ORDER.put("fact", new String[][]{
            {"id","id"},{"about","about"},{"asserted","asserted"},
            {"origin","origin"},{"polarity","polarity"},{"hash","hash"},
            {"valid_from","valid-from"},{"valid_to","valid-to"},{"derived_from","derived-from"}});
        ATTR_ORDER.put("rule", new String[][]{
            {"id","id"},{"origin","origin"},{"valid_from","valid-from"},{"valid_to","valid-to"}});
    }

    private static String escAttr(Object v) {
        return String.valueOf(v).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\"", "&quot;");
    }

    private static String escText(Object v) {
        return String.valueOf(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    private static String fmtNum(Object v) {
        Double d = asDouble(v);
        if (d == null) return String.valueOf(v);
        return d == Math.rint(d) ? String.valueOf((long) (double) d) : String.valueOf(d);
    }

    @SuppressWarnings("unchecked")
    public static String toXml(Map<String, Object> model, int indent) {
        StringBuilder pad = new StringBuilder();
        for (int i = 0; i < indent; i++) pad.append(' ');
        String p1 = pad.toString(), p2 = p1 + p1;

        List<String> out = new ArrayList<>();
        out.add("<?xml version=\"1.0\" encoding=\"UTF-8\"?>");
        out.add("<aodm:knowledge version=\""
                + escAttr(model.getOrDefault("aodm_version", VERSION))
                + "\" xmlns:aodm=\"" + NS + "\">");

        for (Map.Entry<String, String> e : COLLECTION.entrySet()) {
            String kind = e.getKey();
            List<Map<String, Object>> list =
                    (List<Map<String, Object>>) model.getOrDefault(e.getValue(), new ArrayList<>());

            for (Map<String, Object> item : list) {
                StringBuilder attrs = new StringBuilder();
                for (String[] pair : ATTR_ORDER.get(kind)) {
                    Object v = item.get(pair[0]);
                    if (v == null || "".equals(v)) continue;
                    if (v instanceof Boolean) {
                        v = ((Boolean) v) ? "true" : "false";
                    } else if ("derived_from".equals(pair[0])) {
                        List<Object> refs = (List<Object>) v;
                        if (refs.isEmpty()) continue;
                        StringBuilder j = new StringBuilder();
                        for (Object r : refs) { if (j.length() > 0) j.append(' '); j.append(r); }
                        v = j.toString();
                    }
                    attrs.append(' ').append(pair[1]).append("=\"").append(escAttr(v)).append('"');
                }

                List<String> body = new ArrayList<>();
                Object text = "fact".equals(kind) ? item.get("statement") : item.get("content");
                if (text != null && !String.valueOf(text).isEmpty()) {
                    body.add(p2 + escText(text));
                }

                if ("rule".equals(kind)) {
                    for (Object c : (List<Object>) item.getOrDefault("conditions", new ArrayList<>())) {
                        String ref, pol = null;
                        if (c instanceof Map) {
                            Map<String, Object> cm = (Map<String, Object>) c;
                            ref = String.valueOf(cm.get("ref"));
                            pol = cm.get("polarity") == null ? null : String.valueOf(cm.get("polarity"));
                        } else ref = String.valueOf(c);
                        body.add(p2 + "<aodm:condition ref=\"" + escAttr(ref) + "\""
                                + (pol != null ? " polarity=\"" + escAttr(pol) + "\"" : "") + "/>");
                    }
                    if (item.get("conclusion") != null) {
                        body.add(p2 + "<aodm:conclusion ref=\"" + escAttr(item.get("conclusion")) + "\"/>");
                    }
                }

                Map<String, Object> val = (Map<String, Object>) item.get("value");
                if (val != null) {
                    StringBuilder a = new StringBuilder();
                    for (String k : new String[]{"number", "min", "max", "tolerance", "unit"}) {
                        Object v = val.get(k);
                        if (v == null) continue;
                        a.append(' ').append(k).append("=\"")
                         .append(escAttr("unit".equals(k) ? v : fmtNum(v))).append('"');
                    }
                    body.add(p2 + "<aodm:value" + a + "/>");
                }
                for (Object evO : (List<Object>) item.getOrDefault("evidence", new ArrayList<>())) {
                    Map<String, Object> ev = (Map<String, Object>) evO;
                    StringBuilder a = new StringBuilder();
                    for (String k : new String[]{"uri", "locator", "retrieved"}) {
                        if (ev.get(k) != null) {
                            a.append(' ').append(k).append("=\"").append(escAttr(ev.get(k))).append('"');
                        }
                    }
                    if (ev.get("excerpt") != null) {
                        body.add(p2 + "<aodm:evidence" + a + ">" + escText(ev.get("excerpt"))
                                + "</aodm:evidence>");
                    } else {
                        body.add(p2 + "<aodm:evidence" + a + "/>");
                    }
                }
                Map<String, Object> src = (Map<String, Object>) item.get("source");
                if (src != null) {
                    StringBuilder a = new StringBuilder();
                    for (String k : new String[]{"uri", "title", "retrieved", "asserted"}) {
                        Object v = src.get(k);
                        if (v != null) a.append(' ').append(k).append("=\"").append(escAttr(v)).append('"');
                    }
                    body.add(p2 + "<aodm:source" + a + "/>");
                }
                if (item.get("confidence") != null) {
                    Object m = item.get("confidence_method");
                    body.add(p2 + "<aodm:confidence value=\"" + escAttr(fmtNum(item.get("confidence")))
                            + "\"" + (m != null ? " method=\"" + escAttr(m) + "\"" : "") + "/>");
                }

                if (body.isEmpty()) {
                    out.add(p1 + "<aodm:" + kind + attrs + "/>");
                } else {
                    out.add(p1 + "<aodm:" + kind + attrs + ">");
                    out.addAll(body);
                    out.add(p1 + "</aodm:" + kind + ">");
                }
            }
        }

        out.add("</aodm:knowledge>");
        return String.join("\n", out);
    }

    /* ---------------------------------------------------------------- */
    /* Parsing                                                          */
    /* ---------------------------------------------------------------- */

    public static Document parse(String xml) {
        if (xml == null || xml.trim().isEmpty()) {
            throw new AodmException("Nothing to parse: empty input.");
        }

        org.w3c.dom.Document dom;
        try {
            DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
            f.setNamespaceAware(true);
            // External entities are not resolved.
            f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
            f.setFeature("http://xml.org/sax/features/external-general-entities", false);
            f.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
            f.setXIncludeAware(false);
            f.setExpandEntityReferences(false);
            DocumentBuilder b = f.newDocumentBuilder();
            b.setErrorHandler(null);
            dom = b.parse(new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new AodmException("Not well-formed XML: " + e.getMessage(), e);
        }

        List<Issue> issues = new ArrayList<>();
        List<Element> all = new ArrayList<>();
        collectElements(dom.getDocumentElement(), all);

        boolean sawNs = false, sawLegacy = false;
        for (Element el : all) {
            if (NS.equals(el.getNamespaceURI())) sawNs = true;
            if (LEGACY_NS.equals(el.getNamespaceURI())) sawLegacy = true;
        }
        if (!sawNs) {
            if (sawLegacy) {
                throw new AodmException("This document uses the v1.1 namespace (" + LEGACY_NS
                        + "). This parser reads AODM 1.2 (" + NS + ").");
            }
            throw new AodmException("No AODM 1.2 elements found. Declare xmlns:aodm=\"" + NS + "\".");
        }

        Map<String, Object> model = new LinkedHashMap<>();
        model.put("aodm_version", VERSION);
        Map<String, Integer> counters = new HashMap<>();

        for (Element el : all) {
            if (!NS.equals(el.getNamespaceURI())) continue;
            String kind = el.getLocalName();
            if (!PRIMITIVES.contains(kind)) continue;

            int index = counters.merge(kind, 1, Integer::sum) - 1;
            String id = attr(el, "id");
            String where = describe(kind, id, index);

            Map<String, Object> item = new LinkedHashMap<>();
            if (id != null) item.put("id", id);

            putIf(item, "polarity", attr(el, "polarity"));
            putIf(item, "origin", attr(el, "origin"));
            putIf(item, "hash", attr(el, "hash"));
            putIf(item, "valid_from", attr(el, "valid-from"));
            putIf(item, "valid_to", attr(el, "valid-to"));

            String derived = attr(el, "derived-from");
            if (derived != null) {
                List<Object> refs = new ArrayList<>();
                for (String s : derived.trim().split("\\s+")) if (!s.isEmpty()) refs.add(s);
                item.put("derived_from", refs);
            }

            readAnnotations(el, item, issues, where);

            switch (kind) {
                case "entity": {
                    if (id == null) {
                        issues.add(Issue.error("XSD", "entity is missing the required id attribute.", where));
                    }
                    String type = attr(el, "type");
                    if (type != null) item.put("type", type);
                    else issues.add(Issue.error("XSD", "entity is missing the required type attribute.", where));
                    putIf(item, "label", attr(el, "label"));

                    boolean hasNested = false;
                    List<Element> desc = new ArrayList<>();
                    collectElements(el, desc);
                    for (Element d : desc) {
                        if (d != el && NS.equals(d.getNamespaceURI()) && PRIMITIVES.contains(d.getLocalName())) {
                            hasNested = true; break;
                        }
                    }
                    String body = hasNested ? "" : textOf(el);
                    if (!body.isEmpty()) item.put("content", body);
                    item.remove("value");
                    break;
                }
                case "relationship": {
                    for (String a : new String[]{"type", "subject", "predicate", "object"}) {
                        String v = attr(el, a);
                        if (v != null) item.put(a, v);
                        else issues.add(Issue.error("XSD",
                                "relationship is missing the required " + a + " attribute.", where));
                    }
                    item.remove("value");
                    break;
                }
                case "fact": {
                    putIf(item, "about", attr(el, "about"));
                    String asserted = attr(el, "asserted");
                    if ("false".equals(asserted) || "0".equals(asserted)) {
                        item.put("asserted", Boolean.FALSE);
                    }
                    item.put("statement", textOf(el));
                    break;
                }
                case "rule": {
                    List<Object> conds = new ArrayList<>();
                    for (Element c : childElements(el)) {
                        if (!NS.equals(c.getNamespaceURI()) || !"condition".equals(c.getLocalName())) continue;
                        String ref = attr(c, "ref");
                        if (ref == null) {
                            issues.add(Issue.error("XSD", "rule has a condition with no ref attribute.", where));
                            continue;
                        }
                        Map<String, Object> cond = new LinkedHashMap<>();
                        cond.put("ref", ref);
                        putIf(cond, "polarity", attr(c, "polarity"));
                        conds.add(cond);
                    }
                    if (conds.isEmpty()) {
                        issues.add(Issue.error("XSD", "rule has no conditions; at least one is required.", where));
                    }
                    item.put("conditions", conds);

                    List<Element> concl = new ArrayList<>();
                    for (Element c : childElements(el)) {
                        if (NS.equals(c.getNamespaceURI()) && "conclusion".equals(c.getLocalName())) concl.add(c);
                    }
                    if (concl.isEmpty()) {
                        issues.add(Issue.error("XSD", "rule has no conclusion; exactly one is required.", where));
                    } else {
                        if (concl.size() > 1) {
                            issues.add(Issue.error("XSD", "rule has " + concl.size()
                                    + " conclusions; exactly one is allowed.", where));
                        }
                        putIf(item, "conclusion", attr(concl.get(0), "ref"));
                    }
                    item.remove("value");
                    break;
                }
                default: break;
            }

            String coll = COLLECTION.get(kind);
            @SuppressWarnings("unchecked")
            List<Object> list = (List<Object>) model.computeIfAbsent(coll, k -> new ArrayList<>());
            list.add(item);
        }

        return new Document(model, issues);
    }

    public static Document parseFile(String path) throws java.io.IOException {
        return parse(new String(Files.readAllBytes(Paths.get(path)), StandardCharsets.UTF_8));
    }

    /* ---------------------------------------------------------------- */
    /* DOM helpers                                                      */
    /* ---------------------------------------------------------------- */

    private static void collectElements(Node n, List<Element> out) {
        if (n instanceof Element) out.add((Element) n);
        NodeList kids = n.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) collectElements(kids.item(i), out);
    }

    private static List<Element> childElements(Element el) {
        List<Element> out = new ArrayList<>();
        NodeList kids = el.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node n = kids.item(i);
            if (n instanceof Element) out.add((Element) n);
        }
        return out;
    }

    private static String attr(Element el, String name) {
        String v = el.getAttribute(name);
        return (v == null || v.isEmpty()) ? null : v;
    }

    private static void putIf(Map<String, Object> m, String k, String v) {
        if (v != null) m.put(k, v);
    }

    /** Text of an element, excluding nested AODM primitives. */
    static final String HASH_ALGORITHM = "sha256";

    static String trim(String text) {
        return text.trim();
    }

    /** Digest of an item's text content, as <algorithm>:<hex> (VALIDATION-RULES H2). */
    public static String contentHash(String text) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] out = md.digest(trim(text).getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(HASH_ALGORITHM).append(':');
            for (byte b : out) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is required by every Java platform", e);
        }
    }

    private static String textOf(Node n) {
        StringBuilder sb = new StringBuilder();
        NodeList kids = n.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node c = kids.item(i);
            if (c.getNodeType() == Node.TEXT_NODE || c.getNodeType() == Node.CDATA_SECTION_NODE) {
                sb.append(c.getNodeValue());
            } else if (c instanceof Element) {
                Element e = (Element) c;
                // Nested AODM elements are excluded.
                if (NS.equals(e.getNamespaceURI())) continue;
                sb.append(textOf(c));
            }
        }
        return trim(sb.toString());
    }

    /** All text inside an element; annotations keep their own content. */
    private static String allText(Node n) {
        StringBuilder sb = new StringBuilder();
        NodeList kids = n.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node c = kids.item(i);
            if (c.getNodeType() == Node.TEXT_NODE || c.getNodeType() == Node.CDATA_SECTION_NODE) {
                sb.append(c.getNodeValue());
            } else if (c instanceof Element) {
                sb.append(allText(c));
            }
        }
        return sb.toString().replaceAll("\\s+", " ").trim();
    }

    private static Object num(String v) {
        if (v == null || v.isEmpty()) return null;
        try {
            double d = Double.parseDouble(v);
            if (d == Math.rint(d) && !Double.isInfinite(d)) return (long) d;
            return d;
        } catch (NumberFormatException e) {
            return v;
        }
    }

    private static void readAnnotations(Element el, Map<String, Object> item,
                                        List<Issue> issues, String where) {
        int seenConf = 0, seenVal = 0;
        for (Element c : childElements(el)) {
            if (!NS.equals(c.getNamespaceURI())) continue;
            String kind = c.getLocalName();

            if ("confidence".equals(kind)) {
                seenConf++;
                if (!item.containsKey("confidence")) {
                    item.put("confidence", num(attr(c, "value")));
                    putIf(item, "confidence_method", attr(c, "method"));
                }
            } else if ("value".equals(kind)) {
                seenVal++;
                if (!item.containsKey("value")) {
                    Map<String, Object> v = new LinkedHashMap<>();
                    for (String a : new String[]{"number", "min", "max", "tolerance"}) {
                        Object n = num(attr(c, a));
                        if (n != null) v.put(a, n);
                    }
                    putIf(v, "unit", attr(c, "unit"));
                    if (!v.isEmpty()) item.put("value", v);
                }
            } else if ("evidence".equals(kind)) {
                Map<String, Object> ev = new LinkedHashMap<>();
                for (String a : new String[]{"uri", "locator", "retrieved"}) {
                    putIf(ev, a, attr(c, a));
                }
                String ex = allText(c);
                if (!ex.isEmpty()) ev.put("excerpt", ex);
                if (!ev.isEmpty()) {
                    @SuppressWarnings("unchecked")
                    List<Object> list = (List<Object>) item.computeIfAbsent(
                            "evidence", k -> new ArrayList<>());
                    list.add(ev);
                }
            } else if ("source".equals(kind)) {
                if (!item.containsKey("source")) {
                    Map<String, Object> s = new LinkedHashMap<>();
                    for (String a : new String[]{"uri", "title", "retrieved", "asserted"}) {
                        putIf(s, a, attr(c, a));
                    }
                    String t = allText(c);
                    if (!t.isEmpty() && !s.containsKey("title")) s.put("title", t);
                    if (!s.isEmpty()) item.put("source", s);
                }
            }
        }
        if (seenConf > 1) {
            issues.add(Issue.error("C1", "Carries " + seenConf
                    + " confidence elements; at most one is allowed.", where));
        }
        if (seenVal > 1) {
            issues.add(Issue.error("C2", "Carries " + seenVal
                    + " value elements; at most one is allowed.", where));
        }
    }

    private static void putIf(Map<String, Object> m, String k, Object v) {
        if (v != null) m.put(k, v);
    }

    private static String describe(String kind, String id, int index) {
        return id != null ? kind + " \"" + id + "\"" : kind + " #" + (index + 1);
    }

    /* ---------------------------------------------------------------- */
    /* Validation                                                       */
    /* ---------------------------------------------------------------- */

    private static boolean isTemporal(String v) {
        return v != null && (DATE_RE.matcher(v).matches() || DATETIME_RE.matcher(v).matches());
    }

    private static long temporalValue(String v) {
        String s = DATE_RE.matcher(v).matches() ? v + "T00:00:00Z" : v;
        try {
            return OffsetDateTime.parse(s).toInstant().toEpochMilli();
        } catch (Exception e) {
            try {
                return OffsetDateTime.of(java.time.LocalDateTime.parse(s), ZoneOffset.UTC)
                        .toInstant().toEpochMilli();
            } catch (Exception e2) { return Long.MIN_VALUE; }
        }
    }

    private static Double asDouble(Object o) {
        if (o instanceof Number) return ((Number) o).doubleValue();
        if (o instanceof String) {
            try { return Double.parseDouble((String) o); } catch (NumberFormatException e) { return null; }
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    public static List<Issue> validateModel(Map<String, Object> model) {
        List<Issue> issues = new ArrayList<>();
        Map<String, Map<String, Object>> byId = new LinkedHashMap<>();
        Map<String, String> kindOf = new HashMap<>();

        for (Map.Entry<String, String> e : COLLECTION.entrySet()) {
            List<Map<String, Object>> list =
                    (List<Map<String, Object>>) model.getOrDefault(e.getValue(), new ArrayList<>());
            for (int i = 0; i < list.size(); i++) {
                Object idObj = list.get(i).get("id");
                if (idObj == null) continue;
                String id = idObj.toString();
                if (byId.containsKey(id)) {
                    issues.add(Issue.error("R5", "Duplicate id \"" + id
                            + "\". Ids must be unique across the whole document, regardless of "
                            + "element type.", describe(e.getKey(), id, i)));
                } else {
                    byId.put(id, list.get(i));
                    kindOf.put(id, e.getKey());
                }
            }
        }

        long now = System.currentTimeMillis();

        for (Map.Entry<String, String> entry : COLLECTION.entrySet()) {
            String kind = entry.getKey();
            List<Map<String, Object>> list =
                    (List<Map<String, Object>>) model.getOrDefault(entry.getValue(), new ArrayList<>());

            for (int i = 0; i < list.size(); i++) {
                Map<String, Object> item = list.get(i);
                String w = describe(kind, item.get("id") == null ? null : item.get("id").toString(), i);

                if ("relationship".equals(kind)) {
                    for (String side : new String[]{"subject", "object"}) {
                        Object refO = item.get(side);
                        if (refO == null) continue;
                        String ref = refO.toString();
                        if (!byId.containsKey(ref)) {
                            issues.add(Issue.error("R1", "The " + side + " \"" + ref
                                    + "\" does not match any entity id in this document.", w));
                        } else if (!"entity".equals(kindOf.get(ref))) {
                            issues.add(Issue.error("R1", "The " + side + " \"" + ref + "\" refers to a "
                                    + kindOf.get(ref) + ", but must refer to an entity.", w));
                        }
                    }
                }

                if ("fact".equals(kind) && item.get("about") != null) {
                    String ref = item.get("about").toString();
                    if (!byId.containsKey(ref)) {
                        issues.add(Issue.error("R2", "about=\"" + ref
                                + "\" does not match any id in this document.", w));
                    } else if (!"entity".equals(kindOf.get(ref)) && !"relationship".equals(kindOf.get(ref))) {
                        issues.add(Issue.error("R2", "about=\"" + ref + "\" refers to a "
                                + kindOf.get(ref) + "; it must refer to an entity or relationship.", w));
                    }
                }

                if ("rule".equals(kind)) {
                    List<Object> conds = (List<Object>) item.getOrDefault("conditions", new ArrayList<>());
                    List<String> refs = new ArrayList<>();
                    for (Object c : conds) {
                        String ref = (c instanceof Map)
                                ? String.valueOf(((Map<String, Object>) c).get("ref"))
                                : String.valueOf(c);
                        refs.add(ref);
                        if (!byId.containsKey(ref)) {
                            issues.add(Issue.error("R3", "Condition ref=\"" + ref
                                    + "\" does not match any id in this document.", w));
                        } else if (!"fact".equals(kindOf.get(ref)) && !"entity".equals(kindOf.get(ref))) {
                            issues.add(Issue.error("R3", "Condition ref=\"" + ref + "\" refers to a "
                                    + kindOf.get(ref) + "; it must refer to a fact or entity.", w));
                        }
                    }
                    Object concl = item.get("conclusion");
                    if (concl != null) {
                        String c = concl.toString();
                        if (!byId.containsKey(c)) {
                            issues.add(Issue.error("R3", "Conclusion ref=\"" + c
                                    + "\" does not match any id in this document.", w));
                        }
                        if (refs.contains(c)) {
                            issues.add(Issue.error("R4", "This rule lists its own conclusion \"" + c
                                    + "\" as a condition. Self-referential rules are not allowed.", w));
                        }
                    }
                }

                for (Object refO : (List<Object>) item.getOrDefault("derived_from", new ArrayList<>())) {
                    String ref = refO.toString();
                    if (!byId.containsKey(ref)) {
                        issues.add(Issue.error("R6", "derived-from references \"" + ref
                                + "\", which does not match any id in this document.", w));
                    } else {
                        String k = kindOf.get(ref);
                        if (!"fact".equals(k) && !"rule".equals(k) && !"entity".equals(k)) {
                            issues.add(Issue.error("R6", "derived-from references a " + k
                                    + "; it must reference a fact, rule, or entity.", w));
                        }
                    }
                }

                Object confO = item.get("confidence");
                if (confO != null) {
                    Double conf = asDouble(confO);
                    if (conf == null) {
                        issues.add(Issue.error("V1", "Confidence is not a number.", w));
                    } else if (conf < 0.0 || conf > 1.0) {
                        issues.add(Issue.error("V1", "Confidence " + trimNum(conf)
                                + " is outside the allowed range 0.0-1.0.", w));
                    } else if (conf < 0.5 && "fact".equals(kind)) {
                        issues.add(Issue.warning("P2", "Confidence is below 0.5. Consumers should be "
                                + "shown that this fact is uncertain.", w));
                    }
                }

                Map<String, Object> src = (Map<String, Object>) item.get("source");
                if (src != null) {
                    for (String k : new String[]{"retrieved", "asserted"}) {
                        Object v = src.get(k);
                        if (v != null && !isTemporal(v.toString())) {
                            issues.add(Issue.error("V2", "source " + k + "=\"" + v
                                    + "\" is not a valid ISO 8601 date.", w));
                        }
                    }
                    Object ret = src.get("retrieved"), ass = src.get("asserted");
                    if (ret != null && isTemporal(ret.toString()) && temporalValue(ret.toString()) > now) {
                        issues.add(Issue.error("V2", "source retrieved=\"" + ret + "\" is in the future.", w));
                    }
                    if (ret != null && ass != null && isTemporal(ret.toString()) && isTemporal(ass.toString())
                            && temporalValue(ass.toString()) > temporalValue(ret.toString())) {
                        issues.add(Issue.error("V2", "source asserted=\"" + ass + "\" is later than retrieved=\""
                                + ret + "\". A source cannot be written after you fetched it.", w));
                    }
                }

                if ("entity".equals(kind) && item.get("type") != null
                        && !TOKEN_RE.matcher(item.get("type").toString()).matches()) {
                    issues.add(Issue.warning("V3", "type=\"" + item.get("type")
                            + "\" should be a lowercase, hyphen-separated token.", w));
                }
                if ("relationship".equals(kind) && item.get("predicate") != null
                        && !TOKEN_RE.matcher(item.get("predicate").toString()).matches()) {
                    issues.add(Issue.warning("V3", "predicate=\"" + item.get("predicate")
                            + "\" should be a lowercase, hyphen-separated token.", w));
                }

                Map<String, Object> val = (Map<String, Object>) item.get("value");
                if (val != null) {
                    boolean hasNum = val.get("number") != null;
                    boolean hasMin = val.get("min") != null;
                    boolean hasMax = val.get("max") != null;
                    if (hasNum && (hasMin || hasMax)) {
                        issues.add(Issue.error("M1", "A value must use either number (a point value) "
                                + "or min and max (a range), not both.", w));
                    } else if (!hasNum && !(hasMin && hasMax)) {
                        issues.add(Issue.error("M1", (hasMin || hasMax)
                                ? "A range value needs both min and max."
                                : "A value must carry either number, or both min and max.", w));
                    }
                    if (hasMin && hasMax) {
                        Double mn = asDouble(val.get("min")), mx = asDouble(val.get("max"));
                        if (mn != null && mx != null && mn > mx) {
                            issues.add(Issue.error("M2", "min (" + trimNum(mn) + ") is greater than max ("
                                    + trimNum(mx) + ").", w));
                        }
                    }
                    if (val.get("tolerance") != null) {
                        Double tol = asDouble(val.get("tolerance"));
                        if (tol != null && tol < 0) {
                            issues.add(Issue.error("M2", "tolerance must not be negative.", w));
                        }
                        if (!hasNum) {
                            issues.add(Issue.error("M2",
                                    "tolerance may only accompany a number, not a min/max range.", w));
                        }
                    }
                    if (val.get("unit") == null && (hasNum || hasMin)) {
                        issues.add(Issue.warning("M3", "This measurement has no unit. Add one (a UCUM "
                                + "code such as Cel, mm, kg, bar) unless the quantity is dimensionless.", w));
                    }
                }

                String[][] temporal = {{"valid_from", "valid-from"}, {"valid_to", "valid-to"}};
                for (String[] p : temporal) {
                    Object v = item.get(p[0]);
                    if (v != null && !isTemporal(v.toString())) {
                        issues.add(Issue.error("T1", p[1] + "=\"" + v
                                + "\" is not a valid ISO 8601 date or date-time.", w));
                    }
                }
                Object vf = item.get("valid_from"), vt = item.get("valid_to");
                if (vf != null && vt != null && isTemporal(vf.toString()) && isTemporal(vt.toString())
                        && temporalValue(vt.toString()) < temporalValue(vf.toString())) {
                    issues.add(Issue.error("T1", "valid-to (" + vt + ") is earlier than valid-from ("
                            + vf + ").", w));
                }

                Object pol = item.get("polarity");
                if (pol != null && !"positive".equals(pol) && !"negative".equals(pol)) {
                    issues.add(Issue.error("N1", "polarity=\"" + pol
                            + "\" is not allowed; use \"positive\" or \"negative\".", w));
                }

                Object hashO = item.get("hash");
                if (hashO != null) {
                    String hash = hashO.toString();
                    if (hash.matches("[0-9a-fA-F]{64}")) {
                        issues.add(Issue.error("H1", "This is a bare hex digest, the v1.1 form. AODM 1.2 "
                                + "requires a named algorithm: \"sha256:" + hash.substring(0, 12) + "...\".", w));
                    } else if (!DIGEST_RE.matcher(hash).matches()) {
                        issues.add(Issue.error("H1", "hash=\"" + hash
                                + "\" is not of the form <algorithm>:<hex-digest>.", w));
                    } else {
                        String algorithm = hash.substring(0, hash.indexOf(':')).toLowerCase();
                        Object bodyO = "fact".equals(kind) ? item.get("statement") : item.get("content");
                        String body = bodyO == null ? "" : bodyO.toString();
                        if (!body.isEmpty() && HASH_ALGORITHM.equals(algorithm)) {
                            String expected = contentHash(body);
                            if (!expected.equalsIgnoreCase(hash)) {
                                issues.add(Issue.error("H4", "hash=\"" + hash + "\" does not match "
                                        + "the digest of this item's text content (" + expected + ").", w));
                            }
                        }
                    }
                }

                if ("generated".equals(item.get("origin"))) {
                    if (item.get("confidence") == null) {
                        issues.add(Issue.error("G3", "origin=\"generated\" marks this a "
                                + "proposal, but it carries no confidence. Nothing states how "
                                + "far it should be trusted.", w));
                    }
                    if (((List<Object>) item.getOrDefault("evidence", new ArrayList<>())).isEmpty()) {
                        issues.add(Issue.warning("G3", "origin=\"generated\" without evidence "
                                + "is unreviewable: nothing shows what prompted the claim.", w));
                    }
                }
                for (Object evO : (List<Object>) item.getOrDefault("evidence", new ArrayList<>())) {
                    if (((Map<String, Object>) evO).get("locator") == null) {
                        issues.add(Issue.warning("G4", "evidence has no locator, so a reviewer "
                                + "must re-read the whole source to check it.", w));
                    }
                }
                if ("derived".equals(item.get("origin"))
                        && ((List<Object>) item.getOrDefault("derived_from", new ArrayList<>())).isEmpty()) {
                    issues.add(Issue.warning("G5", "origin=\"derived\" but nothing named in "
                            + "derived-from; the claim cannot be explained or retracted.", w));
                }

                if ("fact".equals(kind) && Boolean.FALSE.equals(item.get("asserted"))
                        && (item.get("source") != null || item.get("confidence") != null)) {
                    issues.add(Issue.warning("A3", "asserted=\"false\" declares the fact "
                            + "unclaimed, yet it carries a source or confidence. One or the "
                            + "other is wrong.", w));
                }

                if (("fact".equals(kind) || "rule".equals(kind))
                        && item.get("source") == null && item.get("confidence") == null
                        && !Boolean.FALSE.equals(item.get("asserted"))
                        && ((List<Object>) item.getOrDefault("derived_from", new ArrayList<>())).isEmpty()) {
                    issues.add(Issue.warning("P1",
                            "No source and no confidence. Consumers should treat this as unverified.", w));
                }
            }
        }

        // R7 — derivation graph must be acyclic
        Map<String, Integer> state = new HashMap<>();
        boolean[] reported = {false};
        for (String id : new ArrayList<>(byId.keySet())) {
            visit(id, new ArrayList<>(), byId, kindOf, state, issues, reported);
        }

        return issues;
    }

    @SuppressWarnings("unchecked")
    private static void visit(String id, List<String> stack,
                              Map<String, Map<String, Object>> byId, Map<String, String> kindOf,
                              Map<String, Integer> state, List<Issue> issues, boolean[] reported) {
        Integer st = state.get(id);
        if (st != null && st == 1) return;
        if (st != null && st == 0) {
            if (!reported[0]) {
                List<String> cycle = new ArrayList<>(stack.subList(stack.indexOf(id), stack.size()));
                cycle.add(id);
                issues.add(Issue.error("R7", "Derivation cycle detected: " + String.join(" -> ", cycle)
                        + ". A fact cannot derive from itself, directly or transitively.", ""));
                reported[0] = true;
            }
            return;
        }
        state.put(id, 0);
        Map<String, Object> node = byId.getOrDefault(id, new LinkedHashMap<>());
        List<String> next = new ArrayList<>(stack);
        next.add(id);
        for (Object r : (List<Object>) node.getOrDefault("derived_from", new ArrayList<>())) {
            visit(r.toString(), next, byId, kindOf, state, issues, reported);
        }
        if ("rule".equals(kindOf.get(id))) {
            for (Object c : (List<Object>) node.getOrDefault("conditions", new ArrayList<>())) {
                String r = (c instanceof Map) ? String.valueOf(((Map<String, Object>) c).get("ref"))
                                              : String.valueOf(c);
                visit(r, next, byId, kindOf, state, issues, reported);
            }
        }
        state.put(id, 1);
    }

    private static String trimNum(double d) {
        return d == Math.rint(d) ? String.valueOf((long) d) : String.valueOf(d);
    }

    /* ---------------------------------------------------------------- */
    /* Minimal JSON writer                                              */
    /* ---------------------------------------------------------------- */

    static final class Json {
        static String write(Object o, int indent) {
            StringBuilder sb = new StringBuilder();
            writeValue(sb, o, indent, 0);
            return sb.toString();
        }

        @SuppressWarnings("unchecked")
        private static void writeValue(StringBuilder sb, Object o, int indent, int depth) {
            if (o == null) { sb.append("null"); return; }
            if (o instanceof Map) {
                Map<String, Object> m = (Map<String, Object>) o;
                if (m.isEmpty()) { sb.append("{}"); return; }
                sb.append('{');
                int i = 0;
                for (Map.Entry<String, Object> e : m.entrySet()) {
                    if (i++ > 0) sb.append(',');
                    nl(sb, indent, depth + 1);
                    writeString(sb, e.getKey());
                    sb.append(':');
                    if (indent > 0) sb.append(' ');
                    writeValue(sb, e.getValue(), indent, depth + 1);
                }
                nl(sb, indent, depth);
                sb.append('}');
                return;
            }
            if (o instanceof List) {
                List<Object> l = (List<Object>) o;
                if (l.isEmpty()) { sb.append("[]"); return; }
                sb.append('[');
                for (int i = 0; i < l.size(); i++) {
                    if (i > 0) sb.append(',');
                    nl(sb, indent, depth + 1);
                    writeValue(sb, l.get(i), indent, depth + 1);
                }
                nl(sb, indent, depth);
                sb.append(']');
                return;
            }
            if (o instanceof Boolean) { sb.append(o); return; }
            if (o instanceof Number) {
                double d = ((Number) o).doubleValue();
                sb.append(d == Math.rint(d) && !(o instanceof Double && ((Double) o) % 1 != 0)
                        ? String.valueOf(((Number) o).longValue()) : String.valueOf(d));
                return;
            }
            writeString(sb, o.toString());
        }

        private static void nl(StringBuilder sb, int indent, int depth) {
            if (indent <= 0) return;
            sb.append('\n');
            for (int i = 0; i < indent * depth; i++) sb.append(' ');
        }

        private static void writeString(StringBuilder sb, String s) {
            sb.append('"');
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"':  sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\n': sb.append("\\n");  break;
                    case '\r': sb.append("\\r");  break;
                    case '\t': sb.append("\\t");  break;
                    default:
                        if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                        else sb.append(c);
                }
            }
            sb.append('"');
        }
    }

    /* ---------------------------------------------------------------- */
    /* CLI                                                              */
    /* ---------------------------------------------------------------- */

    public static void main(String[] args) throws Exception {
        boolean validateOnly = false;
        String path = null;
        for (String a : args) {
            if ("--validate".equals(a) || "-v".equals(a)) validateOnly = true;
            else if (!a.startsWith("-")) path = a;
        }
        if (path == null) {
            System.err.println("usage: java Aodm [--validate] <file.xml>");
            System.exit(2);
        }

        Document doc;
        try {
            doc = parseFile(path);
        } catch (AodmException e) {
            System.err.println("error: " + e.getMessage());
            System.exit(1);
            return;
        }

        List<Issue> issues = doc.validate();
        int errors = doc.errors().size(), warnings = doc.warnings().size();

        if (Arrays.asList(args).contains("--xml")) {
            System.out.println(doc.toXml());
            System.exit(doc.errors().isEmpty() ? 0 : 1);
        }

        if (validateOnly) {
            for (Issue i : issues) {
                if ("error".equals(i.severity)) System.err.println(i); else System.out.println(i);
            }
            StringBuilder counts = new StringBuilder();
            for (String coll : COLLECTION.values()) {
                int n = doc.collection(coll).size();
                if (n > 0) counts.append(counts.length() > 0 ? ", " : "").append(n).append(' ').append(coll);
            }
            System.out.println("\n" + (counts.length() > 0 ? counts : "empty document")
                    + " — " + errors + " error(s), " + warnings + " warning(s)");
        } else {
            System.out.println(doc.toJson());
        }
        System.exit(errors > 0 ? 1 : 0);
    }
}
