
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) module.exports = factory();
  else root.AODMParser = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var NS = 'http://fucaspark.com/aodm/1.2';
  var LEGACY_NS = 'http://fucaspark.com/aodm';
  var VERSION = '1.2';
  var HASH_ALGORITHM = 'sha256';

  var PRIMITIVES = ['entity', 'relationship', 'fact', 'rule'];
  var COLLECTION = {
    entity: 'entities', relationship: 'relationships',
    fact: 'facts', rule: 'rules'
  };

  var DIGEST_RE = /^[a-z0-9-]+:[0-9a-fA-F]{32,128}$/;
  var TOKEN_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
  var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  var DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/;

  function AodmError(message) {
    var e = new Error(message);
    e.name = 'AodmError';
    return e;
  }

  function isTemporal(v) { return DATE_RE.test(v) || DATETIME_RE.test(v); }

  function temporalValue(v) {
    if (!isTemporal(v)) return null;
    var t = Date.parse(DATE_RE.test(v) ? v + 'T00:00:00Z' : v);
    return isNaN(t) ? null : t;
  }

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    return isNaN(n) ? v : n;
  }

  function describe(kind, id, index) {
    return id ? kind + ' "' + id + '"' : kind + ' #' + (index + 1);
  }

  function parseXmlFallback(xml) {
    var i = 0, root = null, stack = [];

    function fail(msg) { throw AodmError('Not well-formed XML: ' + msg); }

    function decode(s) {
      return s.replace(/&(lt|gt|amp|quot|apos|#x?[0-9a-fA-F]+);/g, function (m, g) {
        switch (g) {
          case 'lt': return '<'; case 'gt': return '>'; case 'amp': return '&';
          case 'quot': return '"'; case 'apos': return "'";
        }
        return g[0] === '#'
          ? String.fromCodePoint(g[1] === 'x' ? parseInt(g.slice(2), 16) : parseInt(g.slice(1), 10))
          : m;
      });
    }

    while (i < xml.length) {
      var lt = xml.indexOf('<', i);
      if (lt === -1) break;

      if (lt > i) {
        var text = xml.slice(i, lt);
        if (stack.length && text.trim()) stack[stack.length - 1].children.push({ text: decode(text) });
        else if (stack.length) stack[stack.length - 1].children.push({ text: text });
      }

      if (xml.startsWith('<!--', lt)) { i = xml.indexOf('-->', lt); if (i === -1) fail('unterminated comment'); i += 3; continue; }
      if (xml.startsWith('<![CDATA[', lt)) {
        var end = xml.indexOf(']]>', lt); if (end === -1) fail('unterminated CDATA');
        if (stack.length) stack[stack.length - 1].children.push({ text: xml.slice(lt + 9, end) });
        i = end + 3; continue;
      }
      if (xml.startsWith('<?', lt) || xml.startsWith('<!', lt)) {
        i = xml.indexOf('>', lt); if (i === -1) fail('unterminated declaration'); i += 1; continue;
      }

      var gt = xml.indexOf('>', lt);
      if (gt === -1) fail('unterminated tag');
      var raw = xml.slice(lt + 1, gt).trim();

      if (raw[0] === '/') {
        var closing = raw.slice(1).trim();
        var top = stack.pop();
        if (!top) fail('unexpected closing tag </' + closing + '>');
        if (top.name !== closing) fail('mismatched tag: <' + top.name + '> closed by </' + closing + '>');
        i = gt + 1; continue;
      }

      var selfClosing = raw.endsWith('/');
      if (selfClosing) raw = raw.slice(0, -1).trim();

      var sp = raw.search(/\s/);
      var name = sp === -1 ? raw : raw.slice(0, sp);
      var attrs = {};
      if (sp !== -1) {
        var re = /([\w:.-]+)\s*=\s*("([^"]*)"|'([^']*)')/g, m;
        while ((m = re.exec(raw.slice(sp)))) attrs[m[1]] = decode(m[3] !== undefined ? m[3] : m[4]);
      }

      var node = { name: name, attrs: attrs, children: [] };
      if (stack.length) stack[stack.length - 1].children.push(node);
      else if (root) fail('multiple root elements');
      else root = node;
      if (!selfClosing) stack.push(node);
      i = gt + 1;
    }

    if (stack.length) fail('unclosed <' + stack[stack.length - 1].name + '>');
    if (!root) fail('no elements found');
    return root;
  }

  function adapt(node, isDom) {
    if (isDom) {
      return {
        localName: node.localName,
        ns: node.namespaceURI,
        attr: function (n) { return node.getAttribute(n); },
        children: Array.prototype.filter.call(node.childNodes, function (c) { return c.nodeType === 1; })
          .map(function (c) { return adapt(c, true); }),
        textNodes: Array.prototype.map.call(node.childNodes, function (c) {
          return c.nodeType === 3 ? c.nodeValue : null;
        })
      };
    }
    var prefixMap = node._nsmap || {};
    var parts = node.name.split(':');
    var local = parts.length > 1 ? parts[1] : parts[0];
    var prefix = parts.length > 1 ? parts[0] : '';
    return {
      localName: local,
      ns: prefixMap[prefix] || '',
      attr: function (n) {
        if (node.attrs[n] !== undefined) return node.attrs[n];
        for (var k in node.attrs) if (k.split(':').pop() === n) return node.attrs[k];
        return null;
      },
      children: node.children.filter(function (c) { return c.name; })
        .map(function (c) { c._nsmap = node._nsmap; return adapt(c, false); }),
      textNodes: node.children.filter(function (c) { return c.text !== undefined; })
        .map(function (c) { return c.text; }),
      _raw: node
    };
  }

  function applyNamespaces(node, inherited) {
    var map = Object.assign({}, inherited);
    for (var k in node.attrs) {
      if (k === 'xmlns') map[''] = node.attrs[k];
      else if (k.indexOf('xmlns:') === 0) map[k.slice(6)] = node.attrs[k];
    }
    node._nsmap = map;
    node.children.forEach(function (c) { if (c.name) applyNamespaces(c, map); });
  }

  var SHA256_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];

  function utf8Bytes(text) {
    if (typeof TextEncoder !== 'undefined') return Array.prototype.slice.call(new TextEncoder().encode(text));
    var out = [], esc = encodeURIComponent(text);
    for (var i = 0; i < esc.length; i++) {
      if (esc.charAt(i) === '%') { out.push(parseInt(esc.substr(i + 1, 2), 16)); i += 2; }
      else out.push(esc.charCodeAt(i));
    }
    return out;
  }

  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }

  function sha256Hex(text) {
    var bytes = utf8Bytes(text);
    var bitLen = bytes.length * 8;
    bytes = bytes.concat([0x80]);
    while (bytes.length % 64 !== 56) bytes.push(0);
    for (var s = 56; s >= 0; s -= 8) bytes.push(Math.floor(bitLen / Math.pow(2, s)) & 0xff);

    var h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
             0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var w = new Array(64);

    for (var i = 0; i < bytes.length; i += 64) {
      for (var t = 0; t < 16; t++) {
        w[t] = (bytes[i + t * 4] << 24) | (bytes[i + t * 4 + 1] << 16)
             | (bytes[i + t * 4 + 2] << 8) | bytes[i + t * 4 + 3];
      }
      for (t = 16; t < 64; t++) {
        var s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3);
        var s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10);
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0;
      }
      var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
      for (t = 0; t < 64; t++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var temp1 = (hh + S1 + ch + SHA256_K[t] + w[t]) | 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var temp2 = (S0 + maj) | 0;
        hh = g; g = f; f = e; e = (d + temp1) | 0;
        d = c; c = b; b = a; a = (temp1 + temp2) | 0;
      }
      h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0; h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
      h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0; h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
    }

    return h.map(function (x) { return ('00000000' + (x >>> 0).toString(16)).slice(-8); }).join('');
  }

  function contentHash(text, algorithm) {
    if (algorithm && algorithm !== HASH_ALGORITHM) throw new Error('unsupported digest algorithm: ' + algorithm);
    return HASH_ALGORITHM + ':' + sha256Hex(trim(text));
  }

  function trim(text) {
    return text.trim();
  }

  function collectText(el) {

    var out = [];
    (function walk(n, isRoot) {
      (n.textNodes || []).forEach(function (t) { if (t) out.push(t); });
      (n.children || []).forEach(function (c) {
        if (c.ns === NS) return;
        walk(c, false);
      });
    })(el, true);
    return trim(out.join(''));
  }

  function allText(el) {
    var out = [];
    (function walk(n) {
      (n.textNodes || []).forEach(function (t) { if (t) out.push(t); });
      (n.children || []).forEach(walk);
    })(el);
    return out.join('').replace(/\s+/g, ' ').trim();
  }

  function readAnnotations(el, issues, where) {
    var out = {}, seenConf = 0, seenVal = 0;
    el.children.forEach(function (c) {
      if (c.ns !== NS) return;
      if (c.localName === 'confidence') {
        seenConf++;
        if (out.confidence === undefined) {
          out.confidence = num(c.attr('value'));
          if (c.attr('method')) out.confidence_method = c.attr('method');
        }
      } else if (c.localName === 'value') {
        seenVal++;
        if (out.value === undefined) {
          var v = {};
          ['number', 'min', 'max', 'tolerance'].forEach(function (a) {
            if (c.attr(a) !== null) v[a] = num(c.attr(a));
          });
          if (c.attr('unit')) v.unit = c.attr('unit');
          if (Object.keys(v).length) out.value = v;
        }
      } else if (c.localName === 'evidence') {
        var ev = {};
        ['uri', 'locator', 'retrieved'].forEach(function (a) {
          if (c.attr(a)) ev[a] = c.attr(a);
        });
        var ex = allText(c);
        if (ex) ev.excerpt = ex;
        if (Object.keys(ev).length) (out.evidence = out.evidence || []).push(ev);
      } else if (c.localName === 'source') {
        if (out.source === undefined) {
          var s = {};
          ['uri', 'title', 'retrieved', 'asserted'].forEach(function (a) {
            if (c.attr(a)) s[a] = c.attr(a);
          });
          var t = allText(c);
          if (t && !s.title) s.title = t;
          if (Object.keys(s).length) out.source = s;
        }
      }
    });
    if (seenConf > 1) issues.push({ rule: 'C1', severity: 'error', where: where,
      message: 'Carries ' + seenConf + ' confidence elements; at most one is allowed.' });
    if (seenVal > 1) issues.push({ rule: 'C2', severity: 'error', where: where,
      message: 'Carries ' + seenVal + ' value elements; at most one is allowed.' });
    return out;
  }

  function parse(xml) {
    if (typeof xml !== 'string' || !xml.trim()) throw AodmError('Nothing to parse: empty input.');

    var rootEl, isDom = false;
    if (typeof DOMParser !== 'undefined') {
      var doc = new DOMParser().parseFromString(xml, 'application/xml');
      var perr = doc.querySelector && doc.querySelector('parsererror');
      if (perr) {
        var msg = (perr.textContent || '')
          .replace(/This page contains the following errors?:\s*/i, '')
          .replace(/Below is a rendering of the page[\s\S]*$/i, '')
          .split('\n')[0].trim() || 'Malformed XML';
        throw AodmError('Not well-formed XML: ' + msg);
      }
      rootEl = adapt(doc.documentElement, true);
      isDom = true;
    } else {
      var tree = parseXmlFallback(xml);
      applyNamespaces(tree, {});
      rootEl = adapt(tree, false);
    }

    var issues = [];
    var seenNs = {};
    (function scan(n) {
      seenNs[n.ns || ''] = true;
      n.children.forEach(scan);
    })(rootEl);

    if (!seenNs[NS]) {
      if (seenNs[LEGACY_NS]) {
        throw AodmError('This document uses the v1.1 namespace (' + LEGACY_NS +
                        '). This parser reads AODM 1.2 (' + NS + ').');
      }
      throw AodmError('No AODM 1.2 elements found. Declare xmlns:aodm="' + NS + '".');
    }

    var model = { aodm_version: VERSION };
    var counters = { entity: 0, relationship: 0, fact: 0, rule: 0 };

    (function walk(el) {
      if (el.ns === NS && PRIMITIVES.indexOf(el.localName) !== -1) {
        var kind = el.localName;
        var index = counters[kind]++;
        var id = el.attr('id');
        var where = describe(kind, id, index);
        var item = {};
        if (id) item.id = id;

        [['polarity', 'polarity'], ['origin', 'origin'], ['hash', 'hash'],
         ['valid-from', 'valid_from'], ['valid-to', 'valid_to']].forEach(function (pair) {
          if (el.attr(pair[0])) item[pair[1]] = el.attr(pair[0]);
        });
        if (el.attr('derived-from')) {
          item.derived_from = el.attr('derived-from').split(/\s+/).filter(Boolean);
        }

        Object.assign(item, readAnnotations(el, issues, where));

        if (kind === 'entity') {
          if (!id) issues.push({ rule: 'XSD', severity: 'error', where: where,
            message: 'entity is missing the required id attribute.' });
          if (el.attr('type')) item.type = el.attr('type');
          else issues.push({ rule: 'XSD', severity: 'error', where: where,
            message: 'entity is missing the required type attribute.' });
          if (el.attr('label')) item.label = el.attr('label');

          var hasNested = false;
          (function look(n) {
            n.children.forEach(function (c) {
              if (c.ns === NS && PRIMITIVES.indexOf(c.localName) !== -1) hasNested = true;
              else look(c);
            });
          })(el);
          var body = hasNested ? '' : collectText(el);
          if (body) item.content = body;
          delete item.value;

        } else if (kind === 'relationship') {
          ['type', 'subject', 'predicate', 'object'].forEach(function (a) {
            if (el.attr(a)) item[a] = el.attr(a);
            else issues.push({ rule: 'XSD', severity: 'error', where: where,
              message: 'relationship is missing the required ' + a + ' attribute.' });
          });
          delete item.value;

        } else if (kind === 'fact') {
          if (el.attr('about')) item.about = el.attr('about');

          if (el.attr('asserted') === 'false' || el.attr('asserted') === '0') {
            item.asserted = false;
          }
          item.statement = collectText(el);

        } else if (kind === 'rule') {
          var conds = [];
          el.children.forEach(function (c) {
            if (c.ns === NS && c.localName === 'condition') {
              var ref = c.attr('ref');
              if (!ref) {
                issues.push({ rule: 'XSD', severity: 'error', where: where,
                  message: 'rule has a condition with no ref attribute.' });
                return;
              }
              var cond = { ref: ref };
              if (c.attr('polarity')) cond.polarity = c.attr('polarity');
              conds.push(cond);
            }
          });
          if (!conds.length) issues.push({ rule: 'XSD', severity: 'error', where: where,
            message: 'rule has no conditions; at least one is required.' });
          item.conditions = conds;

          var concl = el.children.filter(function (c) {
            return c.ns === NS && c.localName === 'conclusion';
          });
          if (!concl.length) {
            issues.push({ rule: 'XSD', severity: 'error', where: where,
              message: 'rule has no conclusion; exactly one is required.' });
          } else {
            if (concl.length > 1) issues.push({ rule: 'XSD', severity: 'error', where: where,
              message: 'rule has ' + concl.length + ' conclusions; exactly one is allowed.' });
            if (concl[0].attr('ref')) item.conclusion = concl[0].attr('ref');
          }
          delete item.value;
        }

        (model[COLLECTION[kind]] = model[COLLECTION[kind]] || []).push(item);
      }
      el.children.forEach(walk);
    })(rootEl);

    return makeDocument(model, issues);
  }

  function parseJSON(text) {
    var data;
    try { data = JSON.parse(text); }
    catch (e) { throw AodmError('Not valid JSON: ' + e.message); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw AodmError('The document root must be a JSON object.');
    }
    return makeDocument(data, []);
  }

  var ATTR_ORDER = {
    entity: [['id','id'],['type','type'],['label','label'],['hash','hash'],
             ['polarity','polarity'],['valid_from','valid-from'],
             ['valid_to','valid-to'],['derived_from','derived-from']],
    relationship: [['id','id'],['type','type'],['subject','subject'],
                   ['predicate','predicate'],['object','object'],
                   ['polarity','polarity'],['origin','origin'],
                   ['valid_from','valid-from'],
                   ['valid_to','valid-to'],['derived_from','derived-from']],
    fact: [['id','id'],['about','about'],['asserted','asserted'],
           ['origin','origin'],['polarity','polarity'],['hash','hash'],
           ['valid_from','valid-from'],['valid_to','valid-to'],
           ['derived_from','derived-from']],
    rule: [['id','id'],['origin','origin'],['valid_from','valid-from'],['valid_to','valid-to']]
  };

  function escAttr(v) {
    return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function escText(v) {
    return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function fmtNum(v) {
    if (typeof v === 'number' && Number.isInteger(v)) return String(v);
    return String(v);
  }

  function toXml(model, indent) {
    var pad = new Array((indent === undefined ? 2 : indent) + 1).join(' ');
    var out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<aodm:knowledge version="' + escAttr(model.aodm_version || VERSION) +
               '" xmlns:aodm="' + NS + '">'];

    function annotations(item, depth) {
      var p = new Array(depth + 1).join(pad), lines = [];
      if (item.value && typeof item.value === 'object') {
        var a = '';
        ['number', 'min', 'max', 'tolerance', 'unit'].forEach(function (k) {
          if (item.value[k] !== undefined && item.value[k] !== null) {
            a += ' ' + k + '="' + escAttr(fmtNum(item.value[k])) + '"';
          }
        });
        lines.push(p + '<aodm:value' + a + '/>');
      }
      (item.evidence || []).forEach(function (ev) {
        var a = '';
        ['uri', 'locator', 'retrieved'].forEach(function (k) {
          if (ev[k]) a += ' ' + k + '="' + escAttr(ev[k]) + '"';
        });
        lines.push(ev.excerpt
          ? p + '<aodm:evidence' + a + '>' + escText(ev.excerpt) + '</aodm:evidence>'
          : p + '<aodm:evidence' + a + '/>');
      });
      if (item.source && typeof item.source === 'object') {
        var s = '';
        ['uri', 'title', 'retrieved', 'asserted'].forEach(function (k) {
          if (item.source[k] !== undefined && item.source[k] !== null) {
            s += ' ' + k + '="' + escAttr(item.source[k]) + '"';
          }
        });
        lines.push(p + '<aodm:source' + s + '/>');
      }
      if (item.confidence !== undefined && item.confidence !== null) {
        var m = item.confidence_method ? ' method="' + escAttr(item.confidence_method) + '"' : '';
        lines.push(p + '<aodm:confidence value="' + escAttr(fmtNum(item.confidence)) + '"' + m + '/>');
      }
      return lines;
    }

    Object.keys(COLLECTION).forEach(function (kind) {
      (model[COLLECTION[kind]] || []).forEach(function (item) {
        var attrs = '';
        ATTR_ORDER[kind].forEach(function (pair) {
          var v = item[pair[0]];
          if (v === undefined || v === null || v === '') return;
          if (pair[0] === 'derived_from') v = v.join(' ');
          else if (typeof v === 'boolean') v = v ? 'true' : 'false';
          attrs += ' ' + pair[1] + '="' + escAttr(v) + '"';
        });

        var body = [];
        var text = kind === 'fact' ? item.statement : item.content;
        if (text) body.push(pad + pad + escText(text));

        if (kind === 'rule') {
          (item.conditions || []).forEach(function (c) {
            var ref = typeof c === 'string' ? c : c.ref;
            var pol = typeof c === 'string' ? null : c.polarity;
            body.push(pad + pad + '<aodm:condition ref="' + escAttr(ref) + '"' +
                      (pol ? ' polarity="' + escAttr(pol) + '"' : '') + '/>');
          });
          if (item.conclusion) {
            body.push(pad + pad + '<aodm:conclusion ref="' + escAttr(item.conclusion) + '"/>');
          }
        }

        body = body.concat(annotations(item, 2));

        if (body.length) {
          out.push(pad + '<aodm:' + kind + attrs + '>');
          out = out.concat(body);
          out.push(pad + '</aodm:' + kind + '>');
        } else {
          out.push(pad + '<aodm:' + kind + attrs + '/>');
        }
      });
    });

    out.push('</aodm:knowledge>');
    return out.join('\n');
  }

  function makeDocument(model, parseIssues) {
    return {
      model: model,
      toJSON: function (indent) { return JSON.stringify(model, null, indent === undefined ? 2 : indent); },

      toXml: function (indent) { return toXml(model, indent); },
      get entities()      { return model.entities || []; },
      get relationships() { return model.relationships || []; },
      get facts()         { return model.facts || []; },
      get rules()         { return model.rules || []; },
      byId: function (id) {
        var found = null;
        Object.keys(COLLECTION).forEach(function (k) {
          (model[COLLECTION[k]] || []).forEach(function (it) { if (it.id === id) found = it; });
        });
        return found;
      },
      validate: function () { return parseIssues.concat(validateModel(model)); },
      errors:   function () { return this.validate().filter(function (i) { return i.severity === 'error'; }); },
      warnings: function () { return this.validate().filter(function (i) { return i.severity === 'warning'; }); },
      isValid:  function () { return this.errors().length === 0; }
    };
  }

  function validateModel(model) {
    var issues = [];
    var byId = {}, kindOf = {};

    function err(rule, message, where) { issues.push({ rule: rule, severity: 'error', message: message, where: where || '' }); }
    function warn(rule, message, where) { issues.push({ rule: rule, severity: 'warning', message: message, where: where || '' }); }

    Object.keys(COLLECTION).forEach(function (kind) {
      (model[COLLECTION[kind]] || []).forEach(function (item, i) {
        if (!item.id) return;
        if (Object.prototype.hasOwnProperty.call(byId, item.id)) {
          err('R5', 'Duplicate id "' + item.id + '". Ids must be unique across the whole ' +
                    'document, regardless of element type.', describe(kind, item.id, i));
        } else { byId[item.id] = item; kindOf[item.id] = kind; }
      });
    });

    Object.keys(COLLECTION).forEach(function (kind) {
      (model[COLLECTION[kind]] || []).forEach(function (item, i) {
        var w = describe(kind, item.id, i);

        if (kind === 'relationship') {
          ['subject', 'object'].forEach(function (side) {
            var ref = item[side];
            if (!ref) return;
            if (!byId[ref]) err('R1', 'The ' + side + ' "' + ref + '" does not match any entity id in this document.', w);
            else if (kindOf[ref] !== 'entity') err('R1', 'The ' + side + ' "' + ref + '" refers to a ' + kindOf[ref] + ', but must refer to an entity.', w);
          });
        }

        if (kind === 'fact' && item.about) {
          if (!byId[item.about]) err('R2', 'about="' + item.about + '" does not match any id in this document.', w);
          else if (['entity', 'relationship'].indexOf(kindOf[item.about]) === -1)
            err('R2', 'about="' + item.about + '" refers to a ' + kindOf[item.about] + '; it must refer to an entity or relationship.', w);
        }

        if (kind === 'rule') {
          (item.conditions || []).forEach(function (c) {
            var ref = typeof c === 'string' ? c : c && c.ref;
            if (!ref) return;
            if (!byId[ref]) err('R3', 'Condition ref="' + ref + '" does not match any id in this document.', w);
            else if (['fact', 'entity'].indexOf(kindOf[ref]) === -1)
              err('R3', 'Condition ref="' + ref + '" refers to a ' + kindOf[ref] + '; it must refer to a fact or entity.', w);
          });
          if (item.conclusion) {
            if (!byId[item.conclusion]) err('R3', 'Conclusion ref="' + item.conclusion + '" does not match any id in this document.', w);
            var refs = (item.conditions || []).map(function (c) { return typeof c === 'string' ? c : c && c.ref; });
            if (refs.indexOf(item.conclusion) !== -1)
              err('R4', 'This rule lists its own conclusion "' + item.conclusion + '" as a condition. Self-referential rules are not allowed.', w);
          }
        }

        (item.derived_from || []).forEach(function (ref) {
          if (!byId[ref]) err('R6', 'derived-from references "' + ref + '", which does not match any id in this document.', w);
          else if (['fact', 'rule', 'entity'].indexOf(kindOf[ref]) === -1)
            err('R6', 'derived-from references a ' + kindOf[ref] + '; it must reference a fact, rule, or entity.', w);
        });

        if (item.confidence !== undefined && item.confidence !== null) {
          if (typeof item.confidence !== 'number' || isNaN(item.confidence)) err('V1', 'Confidence is not a number.', w);
          else if (item.confidence < 0 || item.confidence > 1) err('V1', 'Confidence ' + item.confidence + ' is outside the allowed range 0.0-1.0.', w);
          else if (item.confidence < 0.5 && kind === 'fact') warn('P2', 'Confidence is below 0.5. Consumers should be shown that this fact is uncertain.', w);
        }

        var src = item.source || {};
        var now = Date.now();
        ['retrieved', 'asserted'].forEach(function (k) {
          if (src[k] && !isTemporal(src[k])) err('V2', 'source ' + k + '="' + src[k] + '" is not a valid ISO 8601 date.', w);
        });
        if (src.retrieved && isTemporal(src.retrieved) && temporalValue(src.retrieved) > now)
          err('V2', 'source retrieved="' + src.retrieved + '" is in the future.', w);
        if (src.asserted && src.retrieved && isTemporal(src.asserted) && isTemporal(src.retrieved)
            && temporalValue(src.asserted) > temporalValue(src.retrieved))
          err('V2', 'source asserted="' + src.asserted + '" is later than retrieved="' + src.retrieved + '". A source cannot be written after you fetched it.', w);

        if (kind === 'entity' && item.type && !TOKEN_RE.test(item.type))
          warn('V3', 'type="' + item.type + '" should be a lowercase, hyphen-separated token.', w);
        if (kind === 'relationship' && item.predicate && !TOKEN_RE.test(item.predicate))
          warn('V3', 'predicate="' + item.predicate + '" should be a lowercase, hyphen-separated token.', w);

        var v = item.value;
        if (v && typeof v === 'object') {
          var hasNum = v.number !== undefined && v.number !== null;
          var hasMin = v.min !== undefined && v.min !== null;
          var hasMax = v.max !== undefined && v.max !== null;
          if (hasNum && (hasMin || hasMax)) err('M1', 'A value must use either number (a point value) or min and max (a range), not both.', w);
          else if (!hasNum && !(hasMin && hasMax)) err('M1', (hasMin || hasMax) ? 'A range value needs both min and max.' : 'A value must carry either number, or both min and max.', w);
          if (hasMin && hasMax && Number(v.min) > Number(v.max)) err('M2', 'min (' + v.min + ') is greater than max (' + v.max + ').', w);
          if (v.tolerance !== undefined && v.tolerance !== null) {
            if (Number(v.tolerance) < 0) err('M2', 'tolerance must not be negative.', w);
            if (!hasNum) err('M2', 'tolerance may only accompany a number, not a min/max range.', w);
          }
          if (!v.unit && (hasNum || hasMin)) warn('M3', 'This measurement has no unit. Add one (a UCUM code such as Cel, mm, kg, bar) unless the quantity is dimensionless.', w);
        }

        [['valid_from', 'valid-from'], ['valid_to', 'valid-to']].forEach(function (p) {
          if (item[p[0]] && !isTemporal(item[p[0]])) err('T1', p[1] + '="' + item[p[0]] + '" is not a valid ISO 8601 date or date-time.', w);
        });
        if (item.valid_from && item.valid_to && isTemporal(item.valid_from) && isTemporal(item.valid_to)
            && temporalValue(item.valid_to) < temporalValue(item.valid_from))
          err('T1', 'valid-to (' + item.valid_to + ') is earlier than valid-from (' + item.valid_from + ').', w);

        if (item.polarity && ['positive', 'negative'].indexOf(item.polarity) === -1)
          err('N1', 'polarity="' + item.polarity + '" is not allowed; use "positive" or "negative".', w);

        if (item.hash) {
          if (/^[0-9a-fA-F]{64}$/.test(item.hash))
            err('H1', 'This is a bare hex digest, the v1.1 form. AODM 1.2 requires a named algorithm: "sha256:' + item.hash.slice(0, 12) + '...".', w);
          else if (!DIGEST_RE.test(item.hash))
            err('H1', 'hash="' + item.hash + '" is not of the form <algorithm>:<hex-digest>.', w);
          else {
            var algorithm = item.hash.split(':')[0].toLowerCase();
            var body = kind === 'fact' ? item.statement : item.content;
            if (body && algorithm === HASH_ALGORITHM) {
              var expected = contentHash(body);
              if (expected.toLowerCase() !== item.hash.toLowerCase())
                err('H4', 'hash="' + item.hash + '" does not match the digest of this '
                        + "item's text content (" + expected + ').', w);
            }
          }
        }

        if (item.origin === 'generated') {
          if (item.confidence === undefined || item.confidence === null)
            err('G3', 'origin="generated" marks this a proposal, but it carries no '
                    + 'confidence. Nothing states how far it should be trusted.', w);
          if (!(item.evidence || []).length)
            warn('G3', 'origin="generated" without evidence is unreviewable: nothing '
                     + 'shows what prompted the claim.', w);
        }
        (item.evidence || []).forEach(function (ev) {
          if (!ev.locator) warn('G4', 'evidence has no locator, so a reviewer must '
                                    + 're-read the whole source to check it.', w);
        });
        if (item.origin === 'derived' && !(item.derived_from || []).length)
          warn('G5', 'origin="derived" but nothing named in derived-from; the claim '
                   + 'cannot be explained or retracted.', w);

        if (kind === 'fact' && item.asserted === false
            && (item.source || item.confidence !== undefined && item.confidence !== null)) {
          warn('A3', 'asserted="false" declares the fact unclaimed, yet it carries a source '
                   + 'or confidence. One or the other is wrong.', w);
        }

        if ((kind === 'fact' || kind === 'rule') && !item.source
            && (item.confidence === undefined || item.confidence === null)
            && !(item.derived_from || []).length && item.asserted !== false)
          warn('P1', 'No source and no confidence. Consumers should treat this as unverified.', w);
      });
    });

    var state = {}, reported = false;
    function visit(id, stack) {
      if (state[id] === 1) return;
      if (state[id] === 0) {
        if (!reported) {
          err('R7', 'Derivation cycle detected: ' + stack.slice(stack.indexOf(id)).concat(id).join(' -> ') +
                    '. A fact cannot derive from itself, directly or transitively.');
          reported = true;
        }
        return;
      }
      state[id] = 0;
      var node = byId[id] || {};
      (node.derived_from || []).forEach(function (r) { visit(r, stack.concat(id)); });
      if (kindOf[id] === 'rule') {
        (node.conditions || []).forEach(function (c) {
          var r = typeof c === 'string' ? c : c && c.ref;
          if (r) visit(r, stack.concat(id));
        });
      }
      state[id] = 1;
    }
    Object.keys(byId).forEach(function (id) { visit(id, []); });

    return issues;
  }

  return {
    parse: parse,
    parseJSON: parseJSON,
    validateModel: validateModel,
    contentHash: contentHash,
    toXml: toXml,
    NS: NS,
    VERSION: VERSION
  };
});
