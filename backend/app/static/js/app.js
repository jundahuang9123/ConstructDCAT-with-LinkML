const payloadEl = document.getElementById('payload');
const validationOutput = document.getElementById('validation-output');
const exportOutput = document.getElementById('export-output');

function readPayload() {
  try {
    return { ok: true, data: JSON.parse(payloadEl.value) };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

async function postJson(url, data) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const text = await res.text();
  try {
    return { status: res.status, body: JSON.parse(text) };
  } catch {
    return { status: res.status, body: text };
  }
}

document.getElementById('load-example').addEventListener('click', () => {
  payloadEl.value = JSON.stringify(window.EXAMPLE_PAYLOAD, null, 2);
});

document.getElementById('validate').addEventListener('click', async () => {
  const parsed = readPayload();
  if (!parsed.ok) {
    validationOutput.textContent = `Invalid JSON: ${parsed.error}`;
    return;
  }
  const res = await postJson('/validate', parsed.data);
  validationOutput.textContent = JSON.stringify(res.body, null, 2);
});

document.getElementById('export-jsonld').addEventListener('click', async () => {
  const parsed = readPayload();
  if (!parsed.ok) {
    exportOutput.textContent = `Invalid JSON: ${parsed.error}`;
    return;
  }
  const res = await postJson('/export/jsonld', parsed.data);
  exportOutput.textContent = JSON.stringify(res.body, null, 2);
});

document.getElementById('export-turtle').addEventListener('click', async () => {
  const parsed = readPayload();
  if (!parsed.ok) {
    exportOutput.textContent = `Invalid JSON: ${parsed.error}`;
    return;
  }
  const res = await postJson('/export/turtle', parsed.data);
  exportOutput.textContent = typeof res.body === 'string' ? res.body : JSON.stringify(res.body, null, 2);
});
