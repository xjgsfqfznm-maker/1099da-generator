/**
 * 1099-DA Draft Generator — Frontend Application
 *
 * Single-page flow:
 *   Step 1: Privacy notice
 *   Step 2: CSV upload
 *   Step 3: Optional donation (5-second countdown skip)
 *   Step 4: Processing (CSV parse → AI → PDF)
 *   Step 5: Download
 *
 * PRIVACY: No analytics, no external requests, no tracking.
 * Session is cleared when user clicks "Start Over" or page unloads after download.
 */

const App = (() => {
  let currentStep = 1;
  let selectedFiles = [];
  let paymentCheckInterval = null;
  let countdownInterval = null;
  let invoiceData = null;
  let taxData = null;

  // ── Navigation ──────────────────────────────────────────────

  function goTo(step) {
    document.querySelectorAll('.card').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('.step').forEach(s => {
      s.classList.remove('active', 'done');
    });

    const sections = ['privacy', 'upload', 'donate', 'process', 'download'];
    const sectionEl = document.getElementById(`section-${sections[step - 1]}`);
    if (sectionEl) sectionEl.classList.add('active');

    for (let i = 1; i <= 5; i++) {
      const stepEl = document.getElementById(`step-indicator-${i}`);
      if (!stepEl) continue;
      if (i < step) stepEl.classList.add('done');
      else if (i === step) stepEl.classList.add('active');
    }

    currentStep = step;
    window.scrollTo({ top: 0, behavior: 'smooth' });

    if (step === 3) initDonationStep();
    if (step === 4) startProcessing();
  }

  // ── Upload Step ──────────────────────────────────────────────

  function handleDragOver(e) {
    e.preventDefault();
    document.getElementById('dropzone').classList.add('over');
  }

  function handleDragLeave(e) {
    document.getElementById('dropzone').classList.remove('over');
  }

  function handleDrop(e) {
    e.preventDefault();
    document.getElementById('dropzone').classList.remove('over');
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.csv'));
    addFiles(files);
  }

  function handleFileSelect(e) {
    addFiles(Array.from(e.target.files));
    e.target.value = '';
  }

  function addFiles(files) {
    for (const f of files) {
      if (selectedFiles.length >= 10) break;
      if (!f.name.toLowerCase().endsWith('.csv')) continue;
      if (!selectedFiles.find(x => x.name === f.name && x.size === f.size)) {
        selectedFiles.push(f);
      }
    }
    renderFileList();
  }

  function removeFile(idx) {
    selectedFiles.splice(idx, 1);
    renderFileList();
  }

  function renderFileList() {
    const list = document.getElementById('fileList');
    const btn = document.getElementById('uploadBtn');

    if (selectedFiles.length === 0) {
      list.innerHTML = '';
      btn.disabled = true;
      return;
    }

    list.innerHTML = selectedFiles.map((f, i) => `
      <div class="file-item">
        <span class="fi-icon">📄</span>
        <span class="fi-name">${escHtml(f.name)}</span>
        <span class="fi-size">${formatBytes(f.size)}</span>
        <button class="fi-remove" onclick="App.removeFile(${i})" title="Remove">✕</button>
      </div>
    `).join('');

    btn.disabled = selectedFiles.length === 0;
  }

  async function uploadFiles() {
    if (selectedFiles.length === 0) return showUploadError('Please add at least one CSV file.');

    const btn = document.getElementById('uploadBtn');
    btn.disabled = true;
    btn.textContent = 'Uploading…';
    hideUploadError();

    const fd = new FormData();
    selectedFiles.forEach(f => fd.append('files', f));

    try {
      const res = await fetch('/upload', { method: 'POST', body: fd });
      const data = await res.json();

      if (!res.ok || !data.success) {
        showUploadError(data.error || 'Upload failed.');
        return;
      }

      if (data.errors && data.errors.length) {
        showUploadError('Some files had issues: ' + data.errors.join(' | '));
      }

      goTo(3);
    } catch (err) {
      showUploadError('Network error: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Upload & Continue →';
    }
  }

  function showUploadError(msg) {
    const el = document.getElementById('uploadError');
    el.textContent = msg;
    el.style.display = 'block';
  }

  function hideUploadError() {
    document.getElementById('uploadError').style.display = 'none';
  }

  // ── Donation Step ──────────────────────────────────────────────

  function initDonationStep() {
    clearCountdown();
    clearPaymentPoll();

    document.getElementById('invoiceSpinner').style.display = 'flex';
    document.getElementById('invoiceContent').style.display = 'none';
    document.getElementById('invoiceError').style.display = 'none';
    document.getElementById('paymentStatus').style.display = 'none';
    document.getElementById('paidBtn').style.display = 'none';
    document.getElementById('skipBtn').disabled = true;

    let secs = 5;
    document.getElementById('skipCountdown').textContent = secs;
    document.getElementById('countdown').textContent = secs;

    countdownInterval = setInterval(() => {
      secs -= 1;
      document.getElementById('skipCountdown').textContent = Math.max(0, secs);
      document.getElementById('countdown').textContent = Math.max(0, secs);
      if (secs <= 0) {
        clearInterval(countdownInterval);
        countdownInterval = null;
        const skipBtn = document.getElementById('skipBtn');
        skipBtn.disabled = false;
        skipBtn.textContent = 'Continue without paying';
      }
    }, 1000);

    fetchInvoice();
  }

  async function fetchInvoice() {
    try {
      const res = await fetch('/donate', { method: 'POST' });
      const data = await res.json();

      document.getElementById('invoiceSpinner').style.display = 'none';

      if (!data.success || !data.payment_request) {
        document.getElementById('invoiceError').textContent =
          'Could not generate invoice: ' + (data.error || 'Unknown error. You can skip this step.');
        document.getElementById('invoiceError').style.display = 'block';
        return;
      }

      invoiceData = data;
      document.getElementById('qrImage').src = data.qr_code;
      document.getElementById('invoiceUri').textContent = data.payment_request.substring(0, 60) + '…';
      document.getElementById('invoiceContent').style.display = 'flex';
      document.getElementById('invoiceContent').style.flexDirection = 'column';
      document.getElementById('invoiceContent').style.alignItems = 'center';
      document.getElementById('invoiceContent').style.gap = '1rem';
      document.getElementById('paidBtn').style.display = 'inline-flex';

      startPaymentPoll();
    } catch (err) {
      document.getElementById('invoiceSpinner').style.display = 'none';
      document.getElementById('invoiceError').textContent = 'Invoice generation error: ' + err.message;
      document.getElementById('invoiceError').style.display = 'block';
    }
  }

  function startPaymentPoll() {
    if (paymentCheckInterval) return;
    paymentCheckInterval = setInterval(async () => {
      try {
        const res = await fetch('/check-payment', { method: 'POST' });
        const data = await res.json();
        if (data.paid) {
          clearPaymentPoll();
          showPaymentSuccess();
        }
      } catch (_) {}
    }, 3000);
  }

  async function checkPayment() {
    try {
      const res = await fetch('/check-payment', { method: 'POST' });
      const data = await res.json();
      if (data.paid) {
        clearPaymentPoll();
        showPaymentSuccess();
      } else {
        showPaymentPending();
      }
    } catch (err) {
      console.error('Payment check error:', err);
    }
  }

  function showPaymentSuccess() {
    clearCountdown();
    clearPaymentPoll();
    const ps = document.getElementById('paymentStatus');
    ps.className = 'payment-status success-box';
    ps.textContent = '✅ Payment confirmed! Thank you for supporting the project.';
    ps.style.display = 'block';
    document.getElementById('skipBtn').disabled = false;
    document.getElementById('skipBtn').textContent = 'Continue →';
    document.getElementById('paidBtn').style.display = 'none';
  }

  function showPaymentPending() {
    const ps = document.getElementById('paymentStatus');
    ps.className = 'payment-status disclaimer-box';
    ps.textContent = '⏳ Payment not yet detected. Please try again in a few seconds.';
    ps.style.display = 'block';
  }

  function skipDonation() {
    clearCountdown();
    clearPaymentPoll();
    goTo(4);
  }

  function copyInvoice() {
    if (invoiceData && invoiceData.payment_request) {
      navigator.clipboard.writeText(invoiceData.payment_request).then(() => {
        const btn = document.querySelector('[onclick="App.copyInvoice()"]');
        if (btn) {
          const orig = btn.textContent;
          btn.textContent = '✓ Copied!';
          setTimeout(() => { btn.textContent = orig; }, 2000);
        }
      });
    }
  }

  function clearCountdown() {
    if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
  }

  function clearPaymentPoll() {
    if (paymentCheckInterval) { clearInterval(paymentCheckInterval); paymentCheckInterval = null; }
  }

  // ── Processing Step ──────────────────────────────────────────────

  async function startProcessing() {
    setProcessState('ps-parse', 'pending');
    setProcessState('ps-ai', 'waiting');
    setProcessState('ps-pdf', 'waiting');
    document.getElementById('processError').style.display = 'none';

    await sleep(400);
    setProcessState('ps-parse', 'complete');
    setProcessState('ps-ai', 'pending');

    try {
      const res = await fetch('/generate', { method: 'POST' });
      const data = await res.json();

      if (!res.ok || !data.success) {
        setProcessState('ps-ai', 'failed');
        showProcessError(data.error || 'Processing failed. Please try again.');
        return;
      }

      taxData = data.tax_data;
      setProcessState('ps-ai', 'complete');
      setProcessState('ps-pdf', 'pending');

      await sleep(600);

      setProcessState('ps-pdf', 'complete');

      await sleep(300);
      renderDownloadStep(data);
      goTo(5);
    } catch (err) {
      setProcessState('ps-ai', 'failed');
      showProcessError('Network error: ' + err.message);
    }
  }

  function setProcessState(id, state) {
    const el = document.getElementById(id);
    if (!el) return;

    const indicator = el.querySelector('.ps-indicator');
    const icons = { pending: '<div class="spinner sm"></div>', waiting: '⏳', complete: '✓', failed: '✗' };

    el.classList.remove('active', 'done');
    if (state === 'pending') {
      el.classList.add('active');
      indicator.className = 'ps-indicator pending';
    } else if (state === 'complete') {
      el.classList.add('done');
      indicator.className = 'ps-indicator complete';
    } else if (state === 'failed') {
      indicator.className = 'ps-indicator failed';
    } else {
      indicator.className = 'ps-indicator waiting';
    }

    indicator.innerHTML = icons[state] || '⏳';
  }

  function showProcessError(msg) {
    const el = document.getElementById('processError');
    el.textContent = msg;
    el.style.display = 'block';
  }

  // ── Download Step ──────────────────────────────────────────────

  function renderDownloadStep(data) {
    const td = data.tax_data;
    const st = td.short_term || {};
    const lt = td.long_term || {};
    const totalGain = (st.gain_loss || 0) + (lt.gain_loss || 0);

    const gainClass = (v) => v < 0 ? 'loss' : 'gain';
    const fmt = (v) => `$${Math.abs(v).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2})}${v < 0 ? ' (loss)' : ''}`;

    document.getElementById('taxSummary').innerHTML = `
      <div class="ts-section-title">Short-Term (held ≤365 days)</div>
      <div class="ts-row"><span class="ts-label">Proceeds</span><span class="ts-value">$${(st.proceeds||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span></div>
      <div class="ts-row"><span class="ts-label">Cost Basis</span><span class="ts-value">$${(st.cost_basis||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span></div>
      <div class="ts-row"><span class="ts-label">Net Gain / Loss</span><span class="ts-value ${gainClass(st.gain_loss||0)}">${fmt(st.gain_loss||0)}</span></div>
      <div class="ts-row"><span class="ts-label">Dispositions</span><span class="ts-value">${st.count||0}</span></div>

      <div class="ts-section-title" style="margin-top:0.5rem">Long-Term (held >365 days)</div>
      <div class="ts-row"><span class="ts-label">Proceeds</span><span class="ts-value">$${(lt.proceeds||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span></div>
      <div class="ts-row"><span class="ts-label">Cost Basis</span><span class="ts-value">$${(lt.cost_basis||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span></div>
      <div class="ts-row"><span class="ts-label">Net Gain / Loss</span><span class="ts-value ${gainClass(lt.gain_loss||0)}">${fmt(lt.gain_loss||0)}</span></div>
      <div class="ts-row"><span class="ts-label">Dispositions</span><span class="ts-value">${lt.count||0}</span></div>

      <div class="ts-section-title" style="margin-top:0.5rem">Total</div>
      <div class="ts-row"><span class="ts-label">Combined Net Gain / Loss</span><span class="ts-value ${gainClass(totalGain)}">${fmt(totalGain)}</span></div>
    `;

    const aiBadge = document.getElementById('aiBadge');
    aiBadge.style.display = 'block';
    aiBadge.textContent = data.used_ai
      ? '🤖 Calculated using Venice AI (kimi-k2-5) with sanitized data'
      : '🧮 Calculated using FIFO fallback (Venice AI unavailable)';
  }

  function startOver() {
    if (!confirm('This will clear all your uploaded data and tax calculations. Are you sure?')) return;
    fetch('/clear-session', { method: 'POST' })
      .finally(() => {
        selectedFiles = [];
        taxData = null;
        invoiceData = null;
        clearCountdown();
        clearPaymentPoll();
        document.getElementById('fileList').innerHTML = '';
        document.getElementById('walletSelect').value = '';
        document.getElementById('uploadBtn').disabled = true;
        hideUploadError();
        goTo(1);
      });
  }

  // ── Utilities ──────────────────────────────────────────────

  function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  // Public API
  return {
    goTo,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleFileSelect,
    removeFile,
    uploadFiles,
    checkPayment,
    skipDonation,
    copyInvoice,
    startOver,
  };
})();
