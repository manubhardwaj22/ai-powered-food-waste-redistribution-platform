/* FoodRescue AI - thin fetch wrapper around the REST API (same origin). */
(function () {
  "use strict";

  const TOKEN_KEY = "fr_token";
  const USER_KEY = "fr_user";

  class ApiError extends Error {
    constructor(status, message, fields) {
      super(message);
      this.status = status;
      this.fields = fields || {};
    }
  }

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try {
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch (e) { /* storage unavailable: session lasts for this page only */ }
  }

  /** Turn FastAPI error payloads (string or 422 list) into a readable message + field map. */
  function parseError(status, data) {
    const fields = {};
    let message = "Something went wrong. Please try again.";
    if (data && typeof data.detail === "string") {
      message = data.detail;
    } else if (data && Array.isArray(data.detail)) {
      const parts = data.detail.map(function (d) {
        const loc = (d.loc || []).filter(function (x) { return x !== "body"; });
        const field = loc[loc.length - 1];
        const msg = String(d.msg || "Invalid value").replace(/^Value error, /, "");
        if (field !== undefined) fields[field] = msg;
        return loc.length ? loc.join(".") + ": " + msg : msg;
      });
      message = parts.join("; ");
    } else if (status === 0) {
      message = "Cannot reach the server. Check that the application is running.";
    }
    return new ApiError(status, message, fields);
  }

  async function request(method, path, body, opts) {
    opts = opts || {};
    const headers = { Accept: "application/json" };
    const token = storageGet(TOKEN_KEY);
    if (token) headers.Authorization = "Bearer " + token;
    let payload;
    if (body instanceof FormData) {
      payload = body;
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, { method: method, headers: headers, body: payload });
    } catch (e) {
      throw parseError(0, null);
    }
    let data = null;
    const text = await res.text();
    if (text) {
      try { data = JSON.parse(text); } catch (e) { data = { detail: text }; }
    }
    if (!res.ok) {
      if (res.status === 401 && !opts.allow401) {
        API.clearSession();
        const here = window.location.pathname.split("/").pop();
        if (here !== "login.html" && here !== "register.html") {
          window.location.href = "login.html?next=" + encodeURIComponent(here + window.location.search);
        }
      }
      throw parseError(res.status, data);
    }
    return data;
  }

  const API = {
    ApiError: ApiError,
    get: function (p) { return request("GET", p); },
    post: function (p, b, o) { return request("POST", p, b === undefined ? {} : b, o); },
    patch: function (p, b) { return request("PATCH", p, b); },
    upload: function (p, formData) { return request("POST", p, formData); },
    token: function () { return storageGet(TOKEN_KEY); },
    user: function () {
      try { return JSON.parse(storageGet(USER_KEY) || "null"); } catch (e) { return null; }
    },
    saveSession: function (tokenResponse) {
      storageSet(TOKEN_KEY, tokenResponse.access_token);
      storageSet(USER_KEY, JSON.stringify(tokenResponse.user));
    },
    clearSession: function () {
      storageSet(TOKEN_KEY, null);
      storageSet(USER_KEY, null);
    },
  };

  window.API = API;
})();
