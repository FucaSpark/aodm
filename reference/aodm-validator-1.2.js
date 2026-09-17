
(function (global) {
  'use strict';

  var NS = 'http://fucaspark.com/aodm/1.2';
  var LEGACY_NS = 'http://fucaspark.com/aodm';

  var HASH_ALGORITHM = 'sha256';
  var DIGEST_RE = /^[a-z0-9-]+:[0-9a-fA-F]{32,128}$/;
  var TOKEN_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
  var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  var DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/;

  function Report() {
    this.errors = [];
    this.warnings = [];
  }
  Report.prototype.error = function (rule, message, where) {
    this.errors.push({ rule: rule, message: message, where: where || '' });
  };
  Report.prototype.warn = function (rule, message, where) {
    this.warnings.push({ rule: rule, message: message, where: where || '' });
  };

  function isTemporal(v) {
    return DATE_RE.test(v) || DATETIME_RE.test(v);
  }

  function temporalValue(v) {

    var s = DATE_RE.test(v) ? v + 'T00:00:00Z' : v;
    var t = Date.parse(s);
    return isNaN(t) ? null : t;
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

  function contentHash(text) {
    return HASH_ALGORITHM + ':' + sha256Hex(trim(text));
  }

  function textOf(el) {
    var out = [];
    var kids = el.childNodes || [];
    for (var i = 0; i < kids.length; i++) {
      var c = kids[i];
      if (c.nodeType === 3 || c.nodeType === 4) out.push(c.nodeValue || '');
      else if (c.nodeType === 1) {
        if (c.namespaceURI === NS || c.namespaceURI === LEGACY_NS) continue;
        out.push(textOf(c));
      }
    }
    return trim(out.join(''));
  }

  function describe(kind, id, index) {
    return id ? kind + ' "' + id + '"' : kind + ' #' + (index + 1);
  }

  function checkSemantics(items, rep) {
    var byId = {};
    var dupes = {};

    items.forEach(function (it) {
      if (!it.id) return;
      if (Object.prototype.hasOwnProperty.call(byId, it.id)) {
        if (!dupes[it.id]) {
          rep.error('R5', 'Duplicate id "' + it.id + '". Ids must be unique across the whole document, regardless of element type.', it.where);
          dupes[it.id] = true;
        }
      } else {
        byId[it.id] = it;
      }
    });

    function resolve(id) {
      return Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null;
    }

    items.forEach(function (it) {

      if (it.kind === 'relationship') {
        ['subject', 'object'].forEach(function (side) {
          var ref = it[side];
          if (!ref) return;
          var target = resolve(ref);
          if (!target) {
            rep.error('R1', 'The ' + side + ' "' + ref + '" does not match any entity id in this document.', it.where);
          } else if (target.kind !== 'entity') {
            rep.error('R1', 'The ' + side + ' "' + ref + '" refers to a ' + target.kind + ', but must refer to an entity.', it.where);
          }
        });
      }

      if (it.kind === 'fact' && it.about) {
        var ab = resolve(it.about);
        if (!ab) {
          rep.error('R2', 'about="' + it.about + '" does not match any id in this document.', it.where);
        } else if (ab.kind !== 'entity' && ab.kind !== 'relationship') {
          rep.error('R2', 'about="' + it.about + '" refers to a ' + ab.kind + '; it must refer to an entity or relationship.', it.where);
        }
      }

      if (it.kind === 'rule') {
        (it.conditions || []).forEach(function (c) {
          var t = resolve(c.ref);
          if (!t) {
            rep.error('R3', 'Condition ref="' + c.ref + '" does not match any id in this document.', it.where);
          } else if (t.kind !== 'fact' && t.kind !== 'entity') {
            rep.error('R3', 'Condition ref="' + c.ref + '" refers to a ' + t.kind + '; it must refer to a fact or entity.', it.where);
          }
        });
        if (it.conclusion) {
          var concl = resolve(it.conclusion);
          if (!concl) {
            rep.error('R3', 'Conclusion ref="' + it.conclusion + '" does not match any id in this document.', it.where);
          }
          var selfRef = (it.conditions || []).some(function (c) { return c.ref === it.conclusion; });
          if (selfRef) {
            rep.error('R4', 'This rule lists its own conclusion "' + it.conclusion + '" as a condition. Self-referential rules are not allowed.', it.where);
          }
        }
      }

      (it.derivedFrom || []).forEach(function (ref) {
        var t = resolve(ref);
        if (!t) {
          rep.error('R6', 'derived-from references "' + ref + '", which does not match any id in this document.', it.where);
        } else if (t.kind !== 'fact' && t.kind !== 'rule' && t.kind !== 'entity') {
          rep.error('R6', 'derived-from references a ' + t.kind + '; it must reference a fact, rule, or entity.', it.where);
        }
      });

      if (it.confidenceCount > 1) {
        rep.error('C1', 'Carries ' + it.confidenceCount + ' confidence elements; at most one is allowed.', it.where);
      }
      if (it.valueCount > 1) {
        rep.error('C2', 'Carries ' + it.valueCount + ' value elements; at most one is allowed.', it.where);
      }

      if (it.confidence !== null && it.confidence !== undefined) {
        if (isNaN(it.confidence)) {
          rep.error('V1', 'Confidence is not a number.', it.where);
        } else if (it.confidence < 0 || it.confidence > 1) {
          rep.error('V1', 'Confidence ' + it.confidence + ' is outside the allowed range 0.0-1.0.', it.where);
        } else if (it.confidence < 0.5 && it.kind === 'fact') {
          rep.warn('P2', 'Confidence is below 0.5. Consumers should be shown that this fact is uncertain.', it.where);
        }
      }

      if (it.source) {
        var now = Date.now();
        if (it.source.retrieved) {
          if (!isTemporal(it.source.retrieved)) {
            rep.error('V2', 'source retrieved="' + it.source.retrieved + '" is not a valid ISO 8601 date.', it.where);
          } else if (temporalValue(it.source.retrieved) > now) {
            rep.error('V2', 'source retrieved="' + it.source.retrieved + '" is in the future.', it.where);
          }
        }
        if (it.source.asserted) {
          if (!isTemporal(it.source.asserted)) {
            rep.error('V2', 'source asserted="' + it.source.asserted + '" is not a valid ISO 8601 date.', it.where);
          } else if (it.source.retrieved && isTemporal(it.source.retrieved) &&
                     temporalValue(it.source.asserted) > temporalValue(it.source.retrieved)) {
            rep.error('V2', 'source asserted="' + it.source.asserted + '" is later than retrieved="' + it.source.retrieved + '". A source cannot be written after you fetched it.', it.where);
          }
        }
      }

      if (it.kind === 'entity' && it.type && !TOKEN_RE.test(it.type)) {
        rep.warn('V3', 'type="' + it.type + '" should be a lowercase, hyphen-separated token (e.g. "component", "part-of").', it.where);
      }
      if (it.kind === 'relationship' && it.predicate && !TOKEN_RE.test(it.predicate)) {
        rep.warn('V3', 'predicate="' + it.predicate + '" should be a lowercase, hyphen-separated token (e.g. "requires", "part-of").', it.where);
      }

      if (it.value) {
        var v = it.value;
        var hasNum = v.number !== null && v.number !== undefined;
        var hasMin = v.min !== null && v.min !== undefined;
        var hasMax = v.max !== null && v.max !== undefined;

        if (hasNum && (hasMin || hasMax)) {
          rep.error('M1', 'A value must use either number (a point value) or min and max (a range), not both.', it.where);
        } else if (!hasNum && !(hasMin && hasMax)) {
          if (hasMin || hasMax) {
            rep.error('M1', 'A range value needs both min and max.', it.where);
          } else {
            rep.error('M1', 'A value must carry either number, or both min and max.', it.where);
          }
        }
        if (hasMin && hasMax && v.min > v.max) {
          rep.error('M2', 'min (' + v.min + ') is greater than max (' + v.max + ').', it.where);
        }
        if (v.tolerance !== null && v.tolerance !== undefined) {
          if (v.tolerance < 0) {
            rep.error('M2', 'tolerance must not be negative.', it.where);
          }
          if (!hasNum) {
            rep.error('M2', 'tolerance may only accompany a number, not a min/max range.', it.where);
          }
        }
        if (!v.unit && (hasNum || hasMin)) {
          rep.warn('M3', 'This measurement has no unit. Add one (a UCUM code such as Cel, mm, kg, bar) unless the quantity is genuinely dimensionless.', it.where);
        }
      }

      ['validFrom', 'validTo'].forEach(function (f) {
        if (it[f] && !isTemporal(it[f])) {
          rep.error('T1', f.replace('valid', 'valid-').toLowerCase() + '="' + it[f] + '" is not a valid ISO 8601 date or date-time.', it.where);
        }
      });
      if (it.validFrom && it.validTo && isTemporal(it.validFrom) && isTemporal(it.validTo)) {
        if (temporalValue(it.validTo) < temporalValue(it.validFrom)) {
          rep.error('T1', 'valid-to (' + it.validTo + ') is earlier than valid-from (' + it.validFrom + ').', it.where);
        }
      }

      if (it.polarity && it.polarity !== 'positive' && it.polarity !== 'negative') {
        rep.error('N1', 'polarity="' + it.polarity + '" is not allowed; use "positive" or "negative".', it.where);
      }

      if (it.hash) {
        if (/^[0-9a-fA-F]{64}$/.test(it.hash)) {
          rep.error('H1', 'This is a bare hex digest, the v1.1 form. AODM 1.2 requires a named algorithm: "sha256:' + it.hash.slice(0, 12) + '...".', it.where);
        } else if (!DIGEST_RE.test(it.hash)) {
          rep.error('H1', 'hash="' + it.hash + '" is not of the form <algorithm>:<hex-digest>.', it.where);
        } else if (it.text && it.hash.split(':')[0].toLowerCase() === HASH_ALGORITHM) {
          var expected = contentHash(it.text);
          if (expected.toLowerCase() !== it.hash.toLowerCase()) {
            rep.error('H4', 'hash="' + it.hash + '" does not match the digest of this item\'s text content (' + expected + ').', it.where);
          }
        }
      }

      if ((it.kind === 'fact' || it.kind === 'rule') && !it.source &&
          (it.confidence === null || it.confidence === undefined) &&
          (!it.derivedFrom || !it.derivedFrom.length)) {
        rep.warn('P1', 'No source and no confidence. Consumers should treat this as unverified.', it.where);
      }
    });

    var state = {};
    var reported = false;
    function visit(id, stack) {
      if (state[id] === 1) return;
      if (state[id] === 0) {
        if (!reported) {
          var cycle = stack.slice(stack.indexOf(id)).concat(id).join(' -> ');
          rep.error('R7', 'Derivation cycle detected: ' + cycle + '. A fact cannot derive from itself, directly or transitively.', '');
          reported = true;
        }
        return;
      }
      state[id] = 0;
      var node = byId[id];
      if (node) {
        (node.derivedFrom || []).forEach(function (ref) {
          visit(ref, stack.concat(id));
        });
        if (node.kind === 'rule' && node.conclusion) {

          (node.conditions || []).forEach(function (c) { visit(c.ref, stack.concat(id)); });
        }
      }
      state[id] = 1;
    }
    Object.keys(byId).forEach(function (id) { visit(id, []); });

    return byId;
  }

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = parseFloat(v);
    return isNaN(n) ? NaN : n;
  }

  function parseXML(text, rep) {
    var doc = new DOMParser().parseFromString(text, 'application/xml');
    var perr = doc.querySelector('parsererror');
    if (perr) {

      var msg = (perr.textContent || '')
        .replace(/This page contains the following errors?:\s*/i, '')
        .replace(/Below is a rendering of the page[\s\S]*$/i, '')
        .split('\n')[0]
        .trim() || 'Malformed XML';
      rep.error('XML', 'This is not well-formed XML: ' + msg, '');
      return null;
    }

    var root = doc.documentElement;
    var used = root.namespaceURI;
    if (used === LEGACY_NS) {
      rep.error('NS', 'This document uses the v1.1 namespace (' + LEGACY_NS + '). This validator checks AODM 1.2 (' + NS + '). The v1.1 embedding profile has its own validator.', '');
      return null;
    }
    if (used !== NS) {

      if (doc.getElementsByTagNameNS(NS, '*').length === 0) {
        rep.error('NS', 'No AODM 1.2 elements found. Declare xmlns:aodm="' + NS + '".', '');
        return null;
      }
    }

    var items = [];

    function annotations(el) {
      var out = {
        confidence: null, confidenceCount: 0,
        value: null, valueCount: 0,
        source: null
      };
      var kids = el.children || [];
      for (var i = 0; i < kids.length; i++) {
        var k = kids[i];
        if (k.namespaceURI !== NS) continue;
        var ln = k.localName;
        if (ln === 'confidence') {
          out.confidenceCount++;
          if (out.confidence === null) out.confidence = num(k.getAttribute('value'));
        } else if (ln === 'value') {
          out.valueCount++;
          if (out.value === null) {
            out.value = {
              number: k.hasAttribute('number') ? num(k.getAttribute('number')) : null,
              min: k.hasAttribute('min') ? num(k.getAttribute('min')) : null,
              max: k.hasAttribute('max') ? num(k.getAttribute('max')) : null,
              tolerance: k.hasAttribute('tolerance') ? num(k.getAttribute('tolerance')) : null,
              unit: k.getAttribute('unit') || null
            };
          }
        } else if (ln === 'source') {
          if (out.source === null) {
            out.source = {
              retrieved: k.getAttribute('retrieved') || null,
              asserted: k.getAttribute('asserted') || null
            };
          }
        }
      }
      return out;
    }

    function idrefs(el, attr) {
      var raw = el.getAttribute(attr);
      if (!raw) return [];
      return raw.split(/\s+/).filter(Boolean);
    }

    function collect(kind) {
      var nodes = doc.getElementsByTagNameNS(NS, kind);
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];

        var ann = annotations(el);
        var id = el.getAttribute('id');
        var item = {
          kind: kind,
          id: id,
          where: describe(kind, id, i),
          type: el.getAttribute('type'),
          about: el.getAttribute('about'),
          subject: el.getAttribute('subject'),
          object: el.getAttribute('object'),
          predicate: el.getAttribute('predicate'),
          polarity: el.getAttribute('polarity'),
          validFrom: el.getAttribute('valid-from'),
          validTo: el.getAttribute('valid-to'),
          hash: el.getAttribute('hash'),
          text: textOf(el),
          derivedFrom: idrefs(el, 'derived-from'),
          confidence: ann.confidence,
          confidenceCount: ann.confidenceCount,
          value: ann.value,
          valueCount: ann.valueCount,
          source: ann.source
        };

        if (kind === 'entity') {
          if (!id) rep.error('XSD', 'entity #' + (i + 1) + ' is missing the required id attribute.', item.where);
          if (!item.type) rep.error('XSD', describe('entity', id, i) + ' is missing the required type attribute.', item.where);
        }
        if (kind === 'relationship') {
          ['type', 'subject', 'predicate', 'object'].forEach(function (a) {
            if (!el.getAttribute(a)) {
              rep.error('XSD', describe('relationship', id, i) + ' is missing the required ' + a + ' attribute.', item.where);
            }
          });
        }
        if (kind === 'rule') {
          item.conditions = [];
          var cs = el.getElementsByTagNameNS(NS, 'condition');
          for (var c = 0; c < cs.length; c++) {
            item.conditions.push({
              ref: cs[c].getAttribute('ref'),
              polarity: cs[c].getAttribute('polarity')
            });
            if (!cs[c].getAttribute('ref')) {
              rep.error('XSD', describe('rule', id, i) + ' has a condition with no ref attribute.', item.where);
            }
          }
          if (!item.conditions.length) {
            rep.error('XSD', describe('rule', id, i) + ' has no conditions; at least one is required.', item.where);
          }
          var concl = el.getElementsByTagNameNS(NS, 'conclusion');
          if (!concl.length) {
            rep.error('XSD', describe('rule', id, i) + ' has no conclusion; exactly one is required.', item.where);
          } else {
            item.conclusion = concl[0].getAttribute('ref');
            if (concl.length > 1) {
              rep.error('XSD', describe('rule', id, i) + ' has ' + concl.length + ' conclusions; exactly one is allowed.', item.where);
            }
          }
        }
        items.push(item);
      }
    }

    ['entity', 'relationship', 'fact', 'rule'].forEach(collect);

    if (!items.length) {
      rep.error('NS', 'No entity, relationship, fact, or rule elements found in the AODM 1.2 namespace.', '');
      return null;
    }
    return items;
  }

  function parseJSON(text, rep) {
    var data;
    try {
      data = JSON.parse(text);
    } catch (err) {
      rep.error('JSON', 'This is not valid JSON: ' + err.message, '');
      return null;
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      rep.error('JSON', 'The document root must be a JSON object.', '');
      return null;
    }
    if (data.aodm_version === undefined) {
      rep.error('JSON', 'Missing the required "aodm_version" field.', '');
    } else if (data.aodm_version !== '1.2') {
      rep.error('JSON', 'aodm_version is "' + data.aodm_version + '"; this validator checks "1.2".', '');
      return null;
    }

    var items = [];
    function push(kind, arr) {
      if (arr === undefined) return;
      if (!Array.isArray(arr)) {
        rep.error('JSON', '"' + kind + '" must be an array.', '');
        return;
      }
      arr.forEach(function (o, i) {
        if (!o || typeof o !== 'object') {
          rep.error('JSON', kind + ' #' + (i + 1) + ' is not an object.', '');
          return;
        }
        var item = {
          kind: kind.replace(/(ie)?s$/, function (m) { return m === 'ies' ? 'y' : ''; }),
          id: o.id || null,
          type: o.type || null,
          about: o.about || null,
          subject: o.subject || null,
          object: o.object || null,
          predicate: o.predicate || null,
          polarity: o.polarity || null,
          validFrom: o.valid_from || null,
          validTo: o.valid_to || null,
          hash: o.hash || null,
          text: o.content || o.statement || null,
          derivedFrom: Array.isArray(o.derived_from) ? o.derived_from : [],
          confidence: (o.confidence === undefined) ? null : o.confidence,
          confidenceCount: (o.confidence === undefined) ? 0 : 1,
          value: o.value || null,
          valueCount: o.value ? 1 : 0,
          source: o.source || null
        };

        item.kind = ({ entities: 'entity', relationships: 'relationship', facts: 'fact', rules: 'rule' })[kind];
        item.where = describe(item.kind, item.id, i);

        if (item.value) {
          item.value = {
            number: item.value.number === undefined ? null : item.value.number,
            min: item.value.min === undefined ? null : item.value.min,
            max: item.value.max === undefined ? null : item.value.max,
            tolerance: item.value.tolerance === undefined ? null : item.value.tolerance,
            unit: item.value.unit || null
          };
        }

        if (item.kind === 'entity') {
          if (!item.id) rep.error('JSON', 'entity #' + (i + 1) + ' is missing the required "id" field.', item.where);
          if (!item.type) rep.error('JSON', item.where + ' is missing the required "type" field.', item.where);
        }
        if (item.kind === 'relationship') {
          ['type', 'subject', 'predicate', 'object'].forEach(function (f) {
            if (!o[f]) rep.error('JSON', item.where + ' is missing the required "' + f + '" field.', item.where);
          });
        }
        if (item.kind === 'fact' && !o.statement) {
          rep.error('JSON', item.where + ' is missing the required "statement" field.', item.where);
        }
        if (item.kind === 'rule') {
          item.conditions = Array.isArray(o.conditions)
            ? o.conditions.map(function (c) {
                return typeof c === 'string' ? { ref: c } : { ref: c && c.ref, polarity: c && c.polarity };
              })
            : [];
          if (!item.conditions.length) {
            rep.error('JSON', item.where + ' needs at least one condition.', item.where);
          }
          item.conclusion = o.conclusion || null;
          if (!item.conclusion) {
            rep.error('JSON', item.where + ' is missing the required "conclusion" field.', item.where);
          }
        }
        items.push(item);
      });
    }

    push('entities', data.entities);
    push('relationships', data.relationships);
    push('facts', data.facts);
    push('rules', data.rules);

    if (!items.length && !rep.errors.length) {
      rep.error('JSON', 'No entities, relationships, facts, or rules found.', '');
      return null;
    }
    return items;
  }

  function validate(text) {
    var rep = new Report();
    var trimmed = (text || '').trim();

    if (!trimmed) {
      rep.error('INPUT', 'Nothing to validate -- paste an AODM document first.', '');
      return { format: null, ok: false, errors: rep.errors, warnings: rep.warnings, counts: {} };
    }

    var isJSON = trimmed.charAt(0) === '{';
    var items = isJSON ? parseJSON(trimmed, rep) : parseXML(trimmed, rep);

    var counts = {};
    if (items) {
      items.forEach(function (i) { counts[i.kind] = (counts[i.kind] || 0) + 1; });
      checkSemantics(items, rep);
    }

    return {
      format: isJSON ? 'JSON' : 'XML',
      ok: rep.errors.length === 0,
      errors: rep.errors,
      warnings: rep.warnings,
      counts: counts
    };
  }

  global.AODM = { validate: validate, NS: NS, VERSION: '1.2' };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = global.AODM;
  }
})(typeof window !== 'undefined' ? window : this);
