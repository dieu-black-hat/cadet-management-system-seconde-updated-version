/* OCMS front-end behaviour. No inline scripts are used (strict CSP). */
(function () {
  "use strict";

  // Sidebar toggle (mobile)
  document.querySelectorAll("[data-toggle-sidebar]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sb = document.getElementById("sidebar");
      if (!sb) return;
      var open = sb.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var sb = document.getElementById("sidebar");
      if (sb) sb.classList.remove("open");
    }
  });

  // Time-of-day greeting on the landing page
  var greet = document.querySelector("[data-greeting]");
  if (greet) {
    var h = new Date().getHours();
    greet.textContent = h < 12 ? "Good morning." : h < 18 ? "Good afternoon." : "Good evening.";
  }

  // Confirmation dialog for destructive / significant actions: <form data-confirm="message">
  var modalEl = document.getElementById("confirmModal");
  var pendingForm = null;
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.dataset.confirmed === "1" || !modalEl || !window.bootstrap) return;
      e.preventDefault();
      pendingForm = form;
      modalEl.querySelector("[data-confirm-text]").textContent = form.dataset.confirm;
      var okBtn = modalEl.querySelector("[data-confirm-ok]");
      okBtn.textContent = form.dataset.confirmLabel || "Confirm";
      okBtn.className = "btn " + (form.dataset.confirmStyle || "btn-primary");
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    });
  });
  if (modalEl) {
    modalEl.querySelector("[data-confirm-ok]").addEventListener("click", function () {
      if (!pendingForm) return;
      if (!pendingForm.reportValidity()) { bootstrap.Modal.getInstance(modalEl).hide(); return; }
      pendingForm.dataset.confirmed = "1";
      bootstrap.Modal.getInstance(modalEl).hide();
      if (pendingForm.requestSubmit) pendingForm.requestSubmit(); else pendingForm.submit();
    });
  }

  // Workflow decision buttons: put the chosen action into the hidden field.
  document.querySelectorAll("[data-action-value]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var form = btn.closest("form");
      form.querySelector("input[name=action]").value = btn.dataset.actionValue;
      var reason = form.querySelector("textarea[name=comment]");
      if (reason) reason.required = btn.dataset.reasonRequired === "1";
      form.dataset.confirm = btn.dataset.confirmText;
      form.dataset.confirmLabel = btn.dataset.label;
      form.dataset.confirmStyle = "btn-" + btn.dataset.style;
      delete form.dataset.confirmed;
    });
  });

  // Platoon dropdown filtered by the selected company
  document.querySelectorAll("select[data-company-select]").forEach(function (companySel) {
    var platoonSel = document.getElementById(companySel.dataset.companySelect);
    if (!platoonSel) return;
    var all = Array.prototype.slice.call(platoonSel.options).map(function (o) {
      return { value: o.value, text: o.text, company: o.dataset.company || "" };
    });
    function sync() {
      var c = companySel.value;
      var current = platoonSel.value;
      platoonSel.innerHTML = "";
      all.forEach(function (o) {
        if (!o.value || !c || o.company === c) {
          var opt = document.createElement("option");
          opt.value = o.value; opt.text = o.text; opt.dataset.company = o.company;
          if (o.value === current) opt.selected = true;
          platoonSel.appendChild(opt);
        }
      });
    }
    companySel.addEventListener("change", sync);
    sync();
  });

  // Auto-submit filter selects
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  // Charts: <canvas data-chart="json-script-id">
  if (window.Chart) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = "#5b6b82";
    Chart.defaults.borderColor = "#e3e8ef";
    document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
      var src = document.getElementById(canvas.dataset.chart);
      if (!src) return;
      var cfg = JSON.parse(src.textContent);
      var palette = ["#13294b", "#b8892b", "#2b4c80", "#7a8ca8", "#1f7a3d", "#b3261e", "#6b4fbb", "#a76a00"];
      (cfg.datasets || []).forEach(function (ds, i) {
        if (!ds.backgroundColor) {
          ds.backgroundColor = cfg.type === "doughnut" || cfg.type === "pie" ? palette : palette[i % palette.length];
        }
        if (cfg.type === "line") { ds.borderColor = ds.borderColor || palette[i % palette.length]; ds.tension = 0.25; ds.fill = false; }
        ds.borderRadius = cfg.type === "bar" ? 3 : undefined;
      });
      new Chart(canvas, {
        type: cfg.type,
        data: { labels: cfg.labels, datasets: cfg.datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: cfg.legend !== false, position: "bottom", labels: { boxWidth: 12 } } },
          scales: cfg.type === "doughnut" || cfg.type === "pie" ? {} :
            { y: { beginAtZero: true, ticks: { precision: 0 }, stacked: !!cfg.stacked }, x: { stacked: !!cfg.stacked, grid: { display: false }, ticks: { precision: 0 } } },
          indexAxis: cfg.horizontal ? "y" : "x"
        }
      });
    });
  }
})();
