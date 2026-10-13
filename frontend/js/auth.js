/* Login and registration pages. */
(function () {
  "use strict";
  const h = function () { return FR.h.apply(null, arguments); };

  function safeNext() {
    const next = new URLSearchParams(window.location.search).get("next") || "";
    // Only allow same-site relative page names (prevents open redirects).
    return /^[a-z-]+\.html(\?[\w=&%-]*)?$/i.test(next) ? next : null;
  }

  function initLogin() {
    const form = FR.$("#login-form");
    const errBox = FR.$("#form-error");
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      errBox.classList.add("hidden");
      const btn = form.querySelector("button[type=submit]");
      FR.busy(btn, true);
      try {
        const res = await API.post("/api/auth/login", { email: form.email.value.trim(), password: form.password.value }, { allow401: true });
        API.saveSession(res);
        window.location.href = safeNext() || FR.HOME[res.user.role];
      } catch (err) {
        errBox.textContent = err.message;
        errBox.classList.remove("hidden");
      } finally {
        FR.busy(btn, false);
      }
    });
    FR.$all("[data-demo]").forEach(function (b) {
      b.addEventListener("click", function () {
        form.email.value = b.dataset.demo;
        form.password.value = "Demo@12345";
        form.password.focus();
      });
    });
  }

  function categoriesInto(container, name) {
    return API.get("/api/meta").then(function (meta) {
      FR.clear(container);
      meta.categories.forEach(function (c) {
        container.appendChild(h("label", { class: "check" }, h("input", { type: "checkbox", name: name, value: c.key }), c.label));
      });
    });
  }

  function initRegister() {
    const form = FR.$("#register-form");
    const errBox = FR.$("#form-error");
    const ngoBox = FR.$("#ngo-fields");
    const volBox = FR.$("#volunteer-fields");
    const orgField = FR.$("#org-field");

    function syncRole() {
      const role = form.role.value;
      ngoBox.classList.toggle("hidden", role !== "ngo");
      volBox.classList.toggle("hidden", role !== "volunteer");
      orgField.classList.toggle("hidden", role === "ngo");
      FR.$all("input, select", ngoBox).forEach(function (i) { i.disabled = role !== "ngo"; });
      FR.$all("input, select", volBox).forEach(function (i) { i.disabled = role !== "volunteer"; });
    }
    const preset = new URLSearchParams(window.location.search).get("role");
    if (preset && form.querySelector('input[name=role][value="' + preset + '"]')) {
      form.querySelector('input[name=role][value="' + preset + '"]').checked = true;
    }
    FR.$all("input[name=role]", form).forEach(function (r) { r.addEventListener("change", syncRole); });
    syncRole();
    categoriesInto(FR.$("#ngo-categories"), "accepted_categories").catch(function (e) { FR.toast(e.message, "error"); });

    FR.$("#ngo-locate").addEventListener("click", function (e) { FR.geolocate(form.ngo_lat, form.ngo_lon, e.currentTarget); });
    FR.$("#vol-locate").addEventListener("click", function (e) { FR.geolocate(form.vol_lat, form.vol_lon, e.currentTarget); });

    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      errBox.classList.add("hidden");
      const role = form.role.value;
      if (form.password.value !== form.password2.value) {
        errBox.textContent = "Passwords do not match.";
        errBox.classList.remove("hidden");
        form.password2.setAttribute("aria-invalid", "true");
        return;
      }
      const body = {
        email: form.email.value.trim(), password: form.password.value, full_name: form.full_name.value.trim(),
        phone: form.phone.value.trim() || null, role: role,
        organization: role === "ngo" ? null : (form.organization.value.trim() || null),
      };
      if (role === "ngo") {
        const cats = FR.$all("input[name=accepted_categories]:checked", form).map(function (c) { return c.value; });
        if (!cats.length) {
          errBox.textContent = "Select at least one food category your organisation can accept.";
          errBox.classList.remove("hidden");
          return;
        }
        body.ngo = {
          org_name: form.org_name.value.trim(), address: form.ngo_address.value.trim(),
          latitude: Number(form.ngo_lat.value), longitude: Number(form.ngo_lon.value),
          priority: Number(form.priority.value), capacity_kg: Number(form.capacity_kg.value || 0),
          demand_kg: Number(form.demand_kg.value || 0), accepted_categories: cats,
          contact_phone: form.phone.value.trim() || null,
        };
      }
      if (role === "volunteer") {
        body.volunteer = {
          area: form.area.value.trim(), latitude: Number(form.vol_lat.value), longitude: Number(form.vol_lon.value),
          is_available: true, vehicle_type: form.vehicle_type.value,
          vehicle_capacity_kg: Number(form.vehicle_capacity_kg.value), max_distance_km: Number(form.max_distance_km.value),
          constraints: form.constraints.value.trim() || null,
        };
      }
      const btn = form.querySelector("button[type=submit]");
      FR.busy(btn, true);
      try {
        const res = await API.post("/api/auth/register", body);
        API.saveSession(res);
        window.location.href = FR.HOME[res.user.role];
      } catch (err) {
        errBox.textContent = err.message;
        errBox.classList.remove("hidden");
        FR.showFieldErrors(form, err);
      } finally {
        FR.busy(btn, false);
      }
    });
  }

  const page = document.body.dataset.page;
  if (page === "login") initLogin();
  if (page === "register") initRegister();
})();
