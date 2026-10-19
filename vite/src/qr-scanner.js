import QrScanner from 'qr-scanner';

const MFID_PATTERN = /^[0-9a-hjkmnp-tv-z]{26}$/;
const RESOURCE_PATH_PATTERN = /\/(?:datasets|samples|instruments?|projects|resources)\/([0-9a-hjkmnp-tv-z]{26})(?:\/|$)/i;

function extractMfid(rawValue) {
    const value = String(rawValue || '').trim();
    const normalizedValue = value.toLowerCase();
    if (MFID_PATTERN.test(normalizedValue)) return normalizedValue;

    let url;
    try {
        url = new URL(value);
    } catch {
        return null;
    }

    const trustedHosts = new Set([window.location.hostname, 'crucible.lbl.gov']);
    if (!['http:', 'https:'].includes(url.protocol) || !trustedHosts.has(url.hostname)) {
        return null;
    }

    return url.pathname.match(RESOURCE_PATH_PATTERN)?.[1]?.toLowerCase() || null;
}

export function initQrScanner() {
    const modalElement = document.getElementById('qrScannerModal');
    const video = document.getElementById('qrScannerVideo');
    const status = document.getElementById('qrScannerStatus');
    const retryButton = document.getElementById('qrScannerRetry');
    const switchButton = document.getElementById('qrScannerSwitch');
    const torchButton = document.getElementById('qrScannerTorch');
    const torchIcon = document.getElementById('qrScannerTorchIcon');
    const torchLabel = document.getElementById('qrScannerTorchLabel');
    const fileInput = document.getElementById('qrScannerFile');
    const manualForm = document.getElementById('qrScannerManualForm');
    const manualInput = document.getElementById('qrScannerMfid');

    if (!modalElement || !video || !window.bootstrap) {
        throw new Error('QR scanner interface is unavailable');
    }

    const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
    let scanner = null;
    let resolving = false;
    let cameras = [];
    let cameraIndex = 0;
    let modalOpen = false;
    let lookupController = null;

    function setStatus(message, tone = 'secondary') {
        status.textContent = message;
        status.className = `alert alert-${tone} py-2 mb-3`;
    }

    function cameraErrorMessage(error) {
        if (!window.isSecureContext) {
            return 'Camera access requires HTTPS or localhost. Upload a QR image or enter the MFID below.';
        }
        if (!navigator.mediaDevices?.getUserMedia) {
            return 'This browser does not expose camera access. Upload a QR image or enter the MFID below.';
        }
        if (error?.name === 'NotAllowedError') {
            return 'Camera permission was denied. Allow camera access, then try again, or use an image.';
        }
        if (error?.name === 'NotFoundError' || String(error).includes('Camera not found')) {
            return 'No camera was found. Upload a QR image or enter the MFID below.';
        }
        return 'The camera could not be started. Try again or use an image.';
    }

    function setTorchState(enabled) {
        torchButton.setAttribute('aria-pressed', String(enabled));
        torchButton.classList.toggle('btn-warning', enabled);
        torchButton.classList.toggle('btn-outline-secondary', !enabled);
        torchIcon.className = `bi ${enabled ? 'bi-lightbulb-fill' : 'bi-lightbulb'} me-1`;
        torchLabel.textContent = enabled ? 'Turn off light' : 'Turn on light';
    }

    async function refreshTorch() {
        setTorchState(false);
        try {
            torchButton.hidden = !(await scanner?.hasFlash());
        } catch {
            torchButton.hidden = true;
        }
    }

    async function resolveMfid(rawValue) {
        if (resolving || !modalOpen) return;
        const mfid = extractMfid(rawValue);
        if (!mfid) {
            resolving = true;
            scanner?.stop();
            retryButton.hidden = false;
            switchButton.hidden = true;
            torchButton.hidden = true;
            setTorchState(false);
            setStatus('This QR code does not contain a valid MFID or recognized Crucible link.', 'warning');
            return;
        }

        resolving = true;
        scanner?.stop();
        retryButton.hidden = true;
        switchButton.hidden = true;
        torchButton.hidden = true;
        setTorchState(false);
        lookupController?.abort();
        lookupController = new AbortController();
        setStatus('MFID scanned. Looking up resource...', 'primary');
        try {
            const response = await fetch(
                window.cgUrl(`/api/resource-location/${encodeURIComponent(mfid)}`),
                {signal: lookupController.signal},
            );
            if (!modalOpen) return;
            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || `Lookup failed (${response.status})`);
            window.location.assign(data.url);
        } catch (error) {
            if (error.name === 'AbortError') return;
            resolving = false;
            retryButton.hidden = false;
            setStatus(error.message || 'The resource could not be opened.', 'danger');
        }
    }

    async function refreshCameras() {
        try {
            cameras = await QrScanner.listCameras();
            const activeCameraId = video.srcObject?.getVideoTracks?.()[0]?.getSettings?.().deviceId;
            const activeIndex = cameras.findIndex(camera => camera.id === activeCameraId);
            cameraIndex = activeIndex >= 0 ? activeIndex : 0;
            switchButton.hidden = cameras.length < 2;
        } catch {
            cameras = [];
            switchButton.hidden = true;
        }
    }

    async function startCamera() {
        resolving = false;
        retryButton.hidden = true;
        switchButton.hidden = true;
        torchButton.hidden = true;
        setTorchState(false);
        setStatus('Requesting camera access...');

        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
            setStatus(cameraErrorMessage(), 'warning');
            return;
        }

        try {
            if (!scanner) {
                scanner = new QrScanner(
                    video,
                    result => resolveMfid(result.data),
                    {
                        preferredCamera: 'environment',
                        maxScansPerSecond: 10,
                        highlightScanRegion: true,
                        highlightCodeOutline: true,
                        returnDetailedScanResult: true,
                    },
                );
            }
            await scanner.start();
            if (!modalOpen) {
                scanner.stop();
                return;
            }
            setStatus('Point the camera at a Crucible QR code.', 'primary');
            await Promise.all([refreshCameras(), refreshTorch()]);
        } catch (error) {
            scanner?.stop();
            retryButton.hidden = false;
            setStatus(cameraErrorMessage(error), 'warning');
        }
    }

    retryButton.addEventListener('click', startCamera);

    switchButton.addEventListener('click', async () => {
        if (cameras.length < 2 || !scanner) return;
        cameraIndex = (cameraIndex + 1) % cameras.length;
        switchButton.disabled = true;
        try {
            if (torchButton.getAttribute('aria-pressed') === 'true') {
                await scanner.turnFlashOff();
                setTorchState(false);
            }
            await scanner.setCamera(cameras[cameraIndex].id);
            await refreshTorch();
        } catch (error) {
            setStatus(cameraErrorMessage(error), 'warning');
        } finally {
            switchButton.disabled = false;
        }
    });

    torchButton.addEventListener('click', async () => {
        if (!scanner) return;
        const enabled = torchButton.getAttribute('aria-pressed') === 'true';
        torchButton.disabled = true;
        try {
            if (enabled) await scanner.turnFlashOff();
            else await scanner.turnFlashOn();
            setTorchState(!enabled);
        } catch {
            torchButton.hidden = true;
            setTorchState(false);
            setStatus('The camera light is not available on this device.', 'warning');
        } finally {
            torchButton.disabled = false;
        }
    });

    fileInput.addEventListener('change', async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        scanner?.stop();
        resolving = false;
        switchButton.hidden = true;
        torchButton.hidden = true;
        setTorchState(false);
        setStatus('Scanning image...');
        try {
            const result = await QrScanner.scanImage(file, {
                returnDetailedScanResult: true,
                alsoTryWithoutScanRegion: true,
            });
            await resolveMfid(result.data);
        } catch (error) {
            setStatus('No readable QR code was found in that image.', 'warning');
        } finally {
            fileInput.value = '';
        }
    });

    manualForm.addEventListener('submit', event => {
        event.preventDefault();
        resolving = false;
        resolveMfid(manualInput.value);
    });

    modalElement.addEventListener('shown.bs.modal', () => {
        modalOpen = true;
        startCamera();
    });
    modalElement.addEventListener('hidden.bs.modal', () => {
        modalOpen = false;
        lookupController?.abort();
        lookupController = null;
        scanner?.stop();
        resolving = false;
        retryButton.hidden = true;
        switchButton.hidden = true;
        torchButton.hidden = true;
        setTorchState(false);
        manualInput.value = '';
    });

    return {
        open() {
            setStatus('Preparing scanner...');
            modal.show();
        },
    };
}
