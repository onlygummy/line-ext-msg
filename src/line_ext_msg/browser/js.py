"""Every ``page.evaluate`` snippet lives here, in one place.

Two rules keep these scripts safe:

1. Playwright passes exactly ONE argument to ``evaluate``. Scripts that
   need several values take a single object and unpack it inside. A
   script that declares two top-level params silently misaligns (the
   first gets the object, the rest undefined) and querySelector throws,
   which surfaces as a bogus "detached" scroll stop. The test suite
   enforces the single-param rule by scanning this module.
2. Selectors are passed in as arguments instead of being interpolated,
   so this module holds no LINE-DOM knowledge. Callers build the args
   object from ``config.selectors``.
"""

# Shared scroll-box picker. Prefers the chat content box when it really
# scrolls, else walks up to the nearest scrollable ancestor. Overlay
# counts because Chrome reports LINE's scroller that way. Scrollability
# is verified by height, never assumed from the selector alone.
PICK_BOX = """const pick = (sel) => {
    const direct = document.querySelector("[class*='chatroomContent-module__content_area']");
    if (direct && direct.scrollHeight > direct.clientHeight + 4) return direct;
    const list = document.querySelector(sel);
    if (!list) return null;
    let sc = list;
    while (sc && sc !== document.body) {
        const ov = getComputedStyle(sc).overflowY;
        if ((ov === 'auto' || ov === 'scroll' || ov === 'overlay') &&
            sc.scrollHeight > sc.clientHeight + 4) return sc;
        sc = sc.parentElement;
    }
    return direct || list;
};"""

# (scrollTop, scrollHeight, clientHeight) of the chosen chat scroll box.
SCROLL_BOX_STATE = """(args) => {
""" + PICK_BOX + """
    const box = pick(args.listSel);
    if (!box) return [-1, -1, -1];
    return [box.scrollTop, box.scrollHeight, box.clientHeight];
}"""

# Which way scrollTop moves toward older history: negative sticks in a
# column-reverse box, a normal box clamps to zero. Restores the position.
PROBE_SCROLL_DIR = """(args) => {
""" + PICK_BOX + """
    const box = pick(args.listSel);
    if (!box) return null;
    const before = box.scrollTop;
    box.scrollTop = before - 1000;
    const after = box.scrollTop;
    box.scrollTop = before;
    return [before, after];
}"""

# Dumb scrollTop setter. All geometry decisions live in Python so there
# is exactly one place to get direction wrong.
SCROLL_SET = """(args) => {
""" + PICK_BOX + """
    const box = pick(args.listSel);
    if (!box) return false;
    box.scrollTop = args.target;
    return true;
}"""

# data-scroll-date anchor of the message list ('' when unreadable).
SCROLL_DATE = """(args) => {
    const list = document.querySelector(args.listSel);
    if (!list) return '';
    return list.getAttribute('data-scroll-date') || '';
}"""

# One-line description of the chosen scroll box, for run logs.
SCROLL_BOX_INFO = """(args) => {
""" + PICK_BOX + """
    const box = pick(args.listSel);
    if (!box) return 'no-box';
    return box.className + ' top=' + box.scrollTop
        + ' h=' + box.scrollHeight + ' ch=' + box.clientHeight;
}"""

# Epoch ms of the first (oldest) rendered message node. 0 when unknown.
OLDEST_EPOCH = """() => {
    const el = document.querySelector('[data-timestamp]');
    if (!el) return 0;
    const v = parseInt(el.getAttribute('data-timestamp') || '0', 10);
    return Number.isFinite(v) ? v : 0;
}"""

# (select-id, timestamp) of rendered rows in DOM order.
RENDERED_KEYS = """(args) => {
    const rows = [];
    for (const part of args.item.split(',')) {
        document.querySelectorAll(part.trim()).forEach(el => rows.push(el));
    }
    return rows.map(el => [
        el.getAttribute('data-message-select-id') || '',
        el.getAttribute('data-timestamp') || '',
    ]);
}"""

# Room rows read in one call: one CDP roundtrip instead of one per field.
ROOMS_BATCH = """(sels) => {
    const pick = (root, sel) => {
        for (const part of sel.split(',')) {
            const el = root.querySelector(part.trim());
            if (el) return (el.textContent || '').trim();
        }
        return '';
    };
    const rows = [];
    for (const part of sels.room_item.split(',')) {
        document.querySelectorAll(part.trim()).forEach(el => rows.push(el));
    }
    return rows.map(el => ({
        mid: el.getAttribute('data-mid') || '',
        name: pick(el, sels.room_name),
        unread: pick(el, sels.room_unread),
        preview: pick(el, sels.room_preview),
        time: pick(el, sels.room_time),
    }));
}"""

# Scroll the room list to its bottom edge so virtualized rows render.
ROOM_SCROLL = """(args) => {
    const lists = [];
    for (const part of args.listSel.split(',')) {
        document.querySelectorAll(part.trim()).forEach(el => lists.push(el));
    }
    const list = lists[0];
    if (!list) return false;
    let sc = list;
    while (sc && sc !== document.body) {
        const st = getComputedStyle(sc);
        if (st.overflowY === 'auto' || st.overflowY === 'scroll' || st.overflowY === 'overlay') break;
        sc = sc.parentElement;
    }
    (sc || list).scrollTop = (sc || list).scrollHeight;
    return true;
}"""

# Fetch a blob: URL inside the page. Returns {data: base64, mime: str}.
FETCH_BLOB = """async (url) => {
    const r = await fetch(url);
    const b = await r.blob();
    const buf = await b.arrayBuffer();
    let bin = '';
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return {data: btoa(bin), mime: b.type};
}"""

# Redacted storage summary used by the diagnostics probe. Key names with
# type and length only; secret values are never returned.
PROBE_STORAGE = """async () => {
    const out = {session: null, local: null, lsKeys: [], lsLens: {},
                 idbs: [], cookieCount: 0, errors: []};
    try {
        if (chrome && chrome.storage && chrome.storage.session) {
            out.session = await chrome.storage.session.get(null);
        } else { out.errors.push('no-session-api'); }
    } catch (e) { out.errors.push('session:' + (e && e.message || e)); }
    try {
        if (chrome && chrome.storage && chrome.storage.local) {
            out.local = await chrome.storage.local.get(null);
        } else { out.errors.push('no-local-api'); }
    } catch (e) { out.errors.push('local:' + (e && e.message || e)); }
    try {
        out.lsKeys = Object.keys(window.localStorage || {});
        for (const k of out.lsKeys) {
            try { out.lsLens[k] = (window.localStorage.getItem(k) || '').length; }
            catch (e) { out.lsLens[k] = -1; }
        }
    } catch (e) { out.errors.push('ls:' + (e && e.message || e)); }
    try {
        if (indexedDB && indexedDB.databases) {
            out.idbs = (await indexedDB.databases()).map(d => d.name || '');
        }
    } catch (e) { out.errors.push('idb:' + (e && e.message || e)); }
    try {
        const c = document.cookie || '';
        out.cookieCount = c ? c.split(';').length : 0;
    } catch (e) { out.errors.push('cookie:' + (e && e.message || e)); }
    return out;
}"""

# Clear localStorage, extension storage, and report before/after counts.
CLEAR_STORAGE = """async () => {
    const o = {lsBefore: 0, idbBefore: []};
    try { o.lsBefore = Object.keys(window.localStorage || {}).length; }
    catch (e) { o.lsErr = String(e).slice(0, 80); }
    try {
        if (indexedDB && indexedDB.databases)
            o.idbBefore = (await indexedDB.databases()).map(d => d.name || '');
    } catch (e) { o.idbErr = String(e).slice(0, 80); }
    try { window.localStorage.clear(); } catch (e) { o.lsErr = String(e).slice(0, 80); }
    try {
        if (window.chrome && chrome.storage && chrome.storage.local)
            await chrome.storage.local.clear();
        if (window.chrome && chrome.storage && chrome.storage.session)
            await chrome.storage.session.clear();
        o.clearedExtStorage = true;
    } catch (e) { o.extErr = String(e).slice(0, 80); }
    try {
        o.lsAfter = Object.keys(window.localStorage || {}).length;
        if (indexedDB && indexedDB.databases)
            o.idbAfter = (await indexedDB.databases()).map(d => d.name || '');
    } catch (e) { o.afterErr = String(e).slice(0, 80); }
    return o;
}"""

# PNG data URI of the login QR canvas. The QR is drawn on a canvas by a
# bundled encoder, so toDataURL is not tainted. Tries the QR container
# first, then any canvas inside the login page, then the largest square
# canvas on the page, because the canvas can move between builds. Returns
# '' when nothing usable is found.
QR_DATA_URL = """(args) => {
    const uriOf = (c) => {
        try { return c.toDataURL('image/png'); } catch (e) { return ''; }
    };
    const pickFrom = (root) => {
        if (!root) return '';
        let best = '';
        let bestArea = 0;
        for (const c of root.querySelectorAll('canvas')) {
            const area = (c.width || 0) * (c.height || 0);
            if (area > bestArea) { bestArea = area; best = uriOf(c); }
        }
        return best;
    };
    try {
        const direct = pickFrom(document.querySelector(args.sel));
        if (direct) return direct;
        const login = pickFrom(document.querySelector(args.pageSel));
        if (login) return login;
        let best = '';
        let bestArea = 0;
        for (const c of document.querySelectorAll('canvas')) {
            const w = c.width || 0;
            const h = c.height || 0;
            if (w < 100 || h < 100 || w !== h) continue;
            const area = w * h;
            if (area > bestArea) { bestArea = area; best = uriOf(c); }
        }
        return best;
    } catch (e) { return ''; }
}"""

# PIN step after a QR scan: the code the user types into the LINE app on
# the phone, plus its instruction text. Returns {pin, desc}.
LOGIN_PIN = """(args) => {
    const text = (sel) => {
        try {
            const el = document.querySelector(sel);
            return el ? (el.textContent || '').trim() : '';
        } catch (e) { return ''; }
    };
    return {pin: text(args.pinSel), desc: text(args.descSel)};
}"""

# Redacted login-page diagnostics for --debug-qr. Only structural facts and
# sizes are returned, never QR content.
QR_DEBUG = """(args) => {
    const shapes = (root) => {
        const out = [];
        if (!root) return out;
        for (const c of root.querySelectorAll('canvas')) {
            out.push([c.width || 0, c.height || 0]);
        }
        return out;
    };
    const dataLen = (c) => {
        try { return c.toDataURL('image/png').length; } catch (e) { return -1; }
    };
    const qrRoot = document.querySelector(args.sel);
    const loginPage = document.querySelector(args.pageSel);
    const firstQr = qrRoot ? qrRoot.querySelector('canvas') : null;
    const pinEl = document.querySelector(args.pinSel);
    return {
        url: location.href,
        hasLoginPage: !!loginPage,
        hasQrRoot: !!qrRoot,
        qrCanvases: shapes(qrRoot),
        pageCanvases: shapes(loginPage),
        qrDataLen: firstQr ? dataLen(firstQr) : -1,
        hasPin: !!pinEl,
        pinLen: pinEl ? (pinEl.textContent || '').trim().length : 0,
        hasEmailForm: !!document.querySelector("[class*='login_form']"),
    };
}"""
