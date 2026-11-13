(() => {
  const colorByCategory = {
    positive: "#28b889",
    negative: "#ee6c76",
    neutral: "#f0ad4e",
  };
  const canvas = document.getElementById("sentimentChart");
  const context = canvas.getContext("2d");
  const legend = document.getElementById("sentimentLegend");
  const tooltip = document.getElementById("chartTooltip");
  const status = document.getElementById("chartStatus");
  const hidden = new Set();
  let chartData = null;
  let slices = [];
  let labels = [];
  let keys = [];
  let colors = [];

  function loadExport() {
    const script = document.createElement("script");
    script.src = `gsentiment.js?refresh=${Date.now()}`;
    script.onload = () => script.remove();
    script.onerror = () => {
      status.textContent = "Could not load gsentiment.js. Refresh after starting the application.";
      script.remove();
    };
    document.head.appendChild(script);
  }

  function draw(data) {
    chartData = data;
    labels = data.labels;
    keys = labels.map((label) => label.toLowerCase());
    colors = keys.map((key) => colorByCategory[key] || "#8792a2");
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(280, canvas.clientWidth || 420);
    const height = Math.min(380, Math.max(300, width * 0.78));
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);

    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.39;
    const active = data.values.map((value, index) => hidden.has(index) ? 0 : value);
    const activeTotal = active.reduce((sum, value) => sum + value, 0);
    let angle = -Math.PI / 2;
    slices = [];

    if (activeTotal === 0) {
      context.beginPath();
      context.arc(centerX, centerY, radius, 0, Math.PI * 2);
      context.fillStyle = "#edf1f6";
      context.fill();
      context.fillStyle = "#778499";
      context.font = "14px Segoe UI, sans-serif";
      context.textAlign = "center";
      context.fillText("No reviews yet", centerX, centerY + 5);
    } else {
      active.forEach((value, index) => {
        if (!value) return;
        const start = angle;
        const end = angle + value / activeTotal * Math.PI * 2;
        context.beginPath();
        context.moveTo(centerX, centerY);
        context.arc(centerX, centerY, radius, start, end);
        context.closePath();
        context.fillStyle = colors[index];
        context.fill();
        context.strokeStyle = "#fff";
        context.lineWidth = 2;
        context.stroke();
        slices.push({ index, start, end, centerX, centerY, radius });
        angle = end;
      });
    }

    context.beginPath();
    context.arc(centerX, centerY, radius * 0.58, 0, Math.PI * 2);
    context.fillStyle = "#fff";
    context.fill();
    context.fillStyle = "#24344c";
    context.font = "700 22px Segoe UI, sans-serif";
    context.textAlign = "center";
    context.fillText(String(data.total), centerX, centerY + 5);
    context.fillStyle = "#778499";
    context.font = "12px Segoe UI, sans-serif";
    context.fillText("analyzed", centerX, centerY + 25);

    legend.replaceChildren();
    labels.forEach((label, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-pressed", String(!hidden.has(index)));
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.backgroundColor = colors[index];
      const category = document.createElement("span");
      category.className = "category";
      category.textContent = label;
      const measure = document.createElement("span");
      measure.className = "measure";
      measure.textContent = `${data.values[index]} · ${data.percentages[keys[index]]}%`;
      button.append(swatch, category, measure);
      button.addEventListener("click", () => {
        if (hidden.has(index)) hidden.delete(index);
        else hidden.add(index);
        draw(chartData);
      });
      legend.appendChild(button);
    });
    status.textContent = `Total analyzed reviews: ${data.total}. Updates automatically from gsentiment.js.`;
  }

  window.addEventListener("sentiment-data-updated", () => {
    const data = window.sentimentData;
    if (
      !data
      || !Array.isArray(data.labels)
      || !Array.isArray(data.values)
      || data.labels.length !== data.values.length
      || data.values.some((value) => !Number.isFinite(value) || value < 0)
      || !Number.isFinite(data.total)
      || !data.percentages
    ) {
      status.textContent = "The exported sentiment data is invalid.";
      return;
    }
    draw(data);
  });

  canvas.addEventListener("mousemove", (event) => {
    const bounds = canvas.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    const chartX = x;
    const chartY = y;
    let hovered = null;
    for (const slice of slices) {
      const dx = chartX - slice.centerX;
      const dy = chartY - slice.centerY;
      if (Math.hypot(dx, dy) > slice.radius * 0.58 && Math.hypot(dx, dy) <= slice.radius) {
        let pointerAngle = Math.atan2(dy, dx);
        while (pointerAngle < -Math.PI / 2) pointerAngle += Math.PI * 2;
        if (pointerAngle >= slice.start && pointerAngle <= slice.end) hovered = slice.index;
      }
    }
    if (hovered === null || !chartData) {
      tooltip.hidden = true;
      return;
    }
    tooltip.textContent = `${labels[hovered]}: ${chartData.values[hovered]} (${chartData.percentages[keys[hovered]]}%)`;
    tooltip.style.left = `${x + 12}px`;
    tooltip.style.top = `${y + 12}px`;
    tooltip.hidden = false;
  });

  canvas.addEventListener("mouseleave", () => { tooltip.hidden = true; });
  window.addEventListener("resize", () => { if (chartData) draw(chartData); });
  loadExport();
  window.setInterval(loadExport, 5000);
})();
