
(function (global) {
  'use strict';

  var PRIMITIVES = { entity: 1, relationship: 1, fact: 1, rule: 1 };
  var ANNOTATIONS = { source: 1, confidence: 1, value: 1, evidence: 1 };

  var compactCache = new Map();

  function compactData(el) {
    if (compactCache.has(el)) return compactCache.get(el);
    var raw = el.getAttribute('data-aodm');
    var out = null;
    if (raw && raw.charAt(0) === '{') {
      try {
        var obj = JSON.parse(raw);
        if (obj && typeof obj === 'object' && !Array.isArray(obj)) out = obj;
      } catch (e) { out = null; }
    }
    compactCache.set(el, out);
    return out;
  }

  function aodmKind(el) {
    if (!el || !el.getAttribute) return null;
    var obj = compactData(el);
    if (obj) {
      for (var k in obj) {
        if (PRIMITIVES[k] || ANNOTATIONS[k]) return k;
      }
      return null;
    }
    var raw = el.getAttribute('data-aodm');
    return raw || null;
  }

  function aodmId(el) {
    var obj = compactData(el);
    if (obj) {
      var kind = aodmKind(el);
      var v = kind ? obj[kind] : null;
      return typeof v === 'string' && v !== '' ? v : (obj.id || null);
    }
    var v = el.getAttribute('data-aodm-id');
    return (v === null || v === '') ? null : v;
  }

  function text(el) {
    var parts = [];
    (function walk(node) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var c = node.childNodes[i];
        if (c.nodeType === 3) {
          parts.push(c.nodeValue);
        } else if (c.nodeType === 1) {
          var kind = aodmKind(c);
          if (kind && PRIMITIVES[kind]) continue;
          walk(c);
        }
      }
    })(el);

    return parts.join('').replace(/\s+/g, ' ').trim();
  }

  function isScopeContainer(el) {
    return el.querySelector('[data-aodm]') !== null;
  }

  function attr(el, name) {
    var v = el.getAttribute('data-aodm-' + name);
    return (v === null || v === '') ? null : v;
  }

  function numAttr(el, name) {
    var v = attr(el, name);
    if (v === null) return null;
    var n = parseFloat(v);
    return isNaN(n) ? v : n;
  }

  function enclosingEntityId(el) {
    var p = el.parentElement;
    while (p) {
      if (aodmKind(p) === 'entity') return aodmId(p);
      p = p.parentElement;
    }
    return null;
  }

  function owningPrimitive(el) {
    var p = el.parentElement;
    while (p) {
      var kind = aodmKind(p);
      if (kind && PRIMITIVES[kind]) return p;
      p = p.parentElement;
    }
    return null;
  }

  function buildSource(el) {
    var src = {};
    ['uri', 'title', 'retrieved', 'asserted'].forEach(function (k) {
      var v = attr(el, k);
      if (v !== null) src[k] = v;
    });

    if (src.uri === undefined && el.tagName === 'A' && el.getAttribute('href')) {
      src.uri = el.getAttribute('href');
    }
    var t = text(el);
    if (t && src.title === undefined) src.title = t;
    return Object.keys(src).length ? src : null;
  }

  function buildValue(el, prefixed) {
    var val = {};
    ['number', 'min', 'max', 'tolerance'].forEach(function (k) {
      var v = numAttr(el, k);
      if (v !== null) val[k] = v;
    });
    var unit = attr(el, 'unit');
    if (unit !== null) val.unit = unit;
    return Object.keys(val).length ? val : null;
  }

  function applyShorthands(el, item) {
    var conf = attr(el, 'confidence');
    if (conf !== null) {
      var n = parseFloat(conf);
      item.confidence = isNaN(n) ? conf : n;
    }

    var origin = attr(el, 'origin');
    if (origin !== null) item.origin = origin;
    if (attr(el, 'asserted') === 'false') item.asserted = false;

    var evUri = attr(el, 'evidence-uri'), evLoc = attr(el, 'evidence-locator');
    if (evUri !== null || evLoc !== null) {
      var evShort = {};
      if (evUri !== null) evShort.uri = evUri;
      if (evLoc !== null) evShort.locator = evLoc;
      var t = text(el);
      if (t) evShort.excerpt = t;
      item.evidence = [evShort];
    }

    var srcShort = {};
    ['uri', 'title', 'retrieved', 'asserted'].forEach(function (k) {
      var v = attr(el, 'source-' + k);
      if (v !== null) srcShort[k] = v;
    });
    if (Object.keys(srcShort).length) item.source = srcShort;

    var valShort = buildValue(el);
    if (valShort) item.value = valShort;
  }

  function itemFromCompact(obj, kind, el) {
    var item = {};
    var id = obj[kind];
    if (typeof id === 'string' && id !== '') item.id = id;
    else if (typeof obj.id === 'string') item.id = obj.id;

    ['about', 'statement', 'content', 'type', 'label', 'subject', 'predicate',
     'object', 'polarity', 'origin', 'hash', 'confidence_method'
    ].forEach(function (k) {
      if (obj[k] !== undefined) item[k] = obj[k];
    });

    [['valid_from', 'valid-from'], ['valid_to', 'valid-to'],
     ['derived_from', 'derived-from']].forEach(function (pair) {
      var v = obj[pair[0]] !== undefined ? obj[pair[0]] : obj[pair[1]];
      if (v !== undefined) item[pair[0]] = v;
    });
    if (typeof item.derived_from === 'string') {
      item.derived_from = item.derived_from.split(/\s+/).filter(Boolean);
    }

    if (obj.asserted === false) item.asserted = false;

    if (obj.source !== undefined) {
      item.source = typeof obj.source === 'string' ? { uri: obj.source } : obj.source;
    }

    if (obj.confidence !== undefined) {
      if (obj.confidence && typeof obj.confidence === 'object') {
        if (obj.confidence.value !== undefined) item.confidence = obj.confidence.value;
        if (obj.confidence.method !== undefined) item.confidence_method = obj.confidence.method;
      } else {
        item.confidence = obj.confidence;
      }
    }

    if (obj.value !== undefined) {
      if (Array.isArray(obj.value)) {
        var v = {};
        if (obj.value[0] !== undefined) v.number = obj.value[0];
        if (obj.value[1] !== undefined) v.unit = obj.value[1];
        if (obj.value[2] !== undefined) v.tolerance = obj.value[2];
        item.value = v;
      } else {
        item.value = obj.value;
      }
    }

    if (obj.evidence !== undefined) {
      item.evidence = Array.isArray(obj.evidence) ? obj.evidence : [obj.evidence];
    }

    if (kind === 'rule') {
      var conds = obj.conditions;
      if (typeof conds === 'string') conds = conds.split(/\s+/).filter(Boolean);
      item.conditions = (conds || []).map(function (ref) {
        if (typeof ref !== 'string') return ref;
        return ref.charAt(0) === '!'
          ? { ref: ref.slice(1), polarity: 'negative' }
          : { ref: ref };
      });
      if (obj.conclusion !== undefined) item.conclusion = obj.conclusion;
    }

    if (kind === 'fact' && item.statement === undefined) {
      item.statement = text(el);
    }
    if (kind === 'entity' && item.content === undefined && !isScopeContainer(el)) {
      var body = text(el);
      if (body) item.content = body;
    }
    if (kind === 'fact' && item.about === undefined) {
      var about = enclosingEntityId(el);
      if (about) item.about = about;
    }

    return item;
  }

  function extract(root) {
    root = root || document;
    var nodes = root.querySelectorAll('[data-aodm]');
    var doc = { aodm_version: '1.2', entities: [], relationships: [], facts: [], rules: [] };
    var byElement = new Map();

    Array.prototype.forEach.call(nodes, function (el) {
      var kind = aodmKind(el);
      if (!PRIMITIVES[kind]) return;

      var compact = compactData(el);
      if (compact) {
        var built = itemFromCompact(compact, kind, el);
        doc[kind === 'entity' ? 'entities'
          : kind === 'relationship' ? 'relationships'
          : kind === 'fact' ? 'facts' : 'rules'].push(built);
        byElement.set(el, built);
        return;
      }

      var item = {};
      var id = attr(el, 'id');
      if (id) item.id = id;

      ['polarity', 'hash'].forEach(function (k) {
        var v = attr(el, k);
        if (v !== null) item[k] = v;
      });
      ['valid-from', 'valid-to'].forEach(function (k) {
        var v = attr(el, k);
        if (v !== null) item[k.replace('-', '_')] = v;
      });
      var derived = attr(el, 'derived-from');
      if (derived) item.derived_from = derived.split(/\s+/).filter(Boolean);

      applyShorthands(el, item);

      if (kind === 'entity') {
        item.type = attr(el, 'type');
        var label = attr(el, 'label');
        if (label) item.label = label;

        if (!isScopeContainer(el)) {
          var body = text(el);
          if (body) item.content = body;
        }

        if (item.type === null) delete item.type;
        delete item.value;
        doc.entities.push(item);

      } else if (kind === 'relationship') {
        ['type', 'subject', 'predicate', 'object'].forEach(function (k) {
          var v = attr(el, k);
          if (v !== null) item[k] = v;
        });
        delete item.value;
        doc.relationships.push(item);

      } else if (kind === 'fact') {
        var about = attr(el, 'about') || enclosingEntityId(el);
        if (about) item.about = about;
        item.statement = text(el);
        doc.facts.push(item);

      } else if (kind === 'rule') {
        var conds = attr(el, 'conditions');
        item.conditions = conds
          ? conds.split(/\s+/).filter(Boolean).map(function (ref) {
              return ref.charAt(0) === '!'
                ? { ref: ref.slice(1), polarity: 'negative' }
                : { ref: ref };
            })
          : [];
        var concl = attr(el, 'conclusion');
        if (concl) item.conclusion = concl;
        delete item.value;
        doc.rules.push(item);
      }

      byElement.set(el, item);
    });

    Array.prototype.forEach.call(nodes, function (el) {
      var kind = aodmKind(el);
      if (!ANNOTATIONS[kind]) return;

      var ownerEl = owningPrimitive(el);
      var owner = ownerEl ? byElement.get(ownerEl) : null;
      if (!owner) return;

      var ann = compactData(el);
      if (ann) {
        var payload = ann[kind];
        if (kind === 'source') {
          if (owner.source === undefined) {
            owner.source = typeof payload === 'string' ? { uri: payload } : payload;
          }
        } else if (kind === 'confidence') {
          owner.confidence = (payload && typeof payload === 'object')
            ? payload.value : payload;
        } else if (kind === 'value') {
          owner.value = Array.isArray(payload)
            ? { number: payload[0], unit: payload[1], tolerance: payload[2] }
            : payload;
        } else if (kind === 'evidence') {
          var evc = typeof payload === 'string' ? { excerpt: payload } : payload;
          (owner.evidence = owner.evidence || []).push(evc);
        }
        return;
      }

      if (kind === 'source') {
        var s = buildSource(el);
        if (s) {

          if (owner.source === undefined) owner.source = s;
        }
      } else if (kind === 'confidence') {
        var v = attr(el, 'value');
        if (v !== null) {
          var n = parseFloat(v);
          owner.confidence = isNaN(n) ? v : n;
        }
      } else if (kind === 'evidence') {
        var ev = {};
        ['uri', 'locator', 'retrieved'].forEach(function (a) {
          var v = attr(el, a);
          if (v !== null) ev[a] = v;
        });
        var ex = text(el);
        if (ex) ev.excerpt = ex;
        if (Object.keys(ev).length) (owner.evidence = owner.evidence || []).push(ev);
      } else if (kind === 'value') {
        var val = buildValue(el);
        if (val) owner.value = val;
      }
    });

    ['entities', 'relationships', 'facts', 'rules'].forEach(function (k) {
      if (!doc[k].length) delete doc[k];
    });

    return doc;
  }

  function validate(root) {
    var model = extract(root);
    if (!global.AODM || typeof global.AODM.validate !== 'function') {
      throw new Error('aodm-validator-1.2.js must be loaded before validating.');
    }
    return {
      model: model,
      result: global.AODM.validate(JSON.stringify(model))
    };
  }

  global.AODMHTML = { extract: extract, validate: validate, VERSION: '1.2' };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = global.AODMHTML;
  }
})(typeof globalThis !== 'undefined' ? globalThis
  : (typeof window !== 'undefined' ? window : this));
