// Function to restart an import
async function restartImport(uploadId) {
    try {
        const response = await fetch(`/api/restart_import/${uploadId}`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        // Start polling for status updates
        pollImportStatus(uploadId);

    } catch (error) {
        console.error('Error restarting import:', error);
        alert('Failed to restart import. Please try again.');
    }
}

// Function to poll import status and update UI
async function pollImportStatus(uploadId) {
    try {
        const response = await fetch(`/admin/import/${uploadId}/status`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        // Get the progress elements
        const progressBar = document.getElementById(`progress-${uploadId}`);
        const progressText = document.getElementById(`progress-text-${uploadId}`);
        const statusBadge = document.getElementById(`status-${uploadId}`);

        if (progressBar && data.progress_percent !== null) {
            progressBar.style.width = `${data.progress_percent}%`;
        }

        if (progressText && data.progress) {
            progressText.textContent = data.progress;
        }

        if (statusBadge) {
            statusBadge.textContent = data.status;
        }

        // Continue polling if still extracting or importing
        if (data.status === 'EXTRACTING' || data.status === 'IMPORTING') {
            setTimeout(() => pollImportStatus(uploadId), 1000);
        } else if (data.status === 'DONE') {
            // Refresh the page to show updated status
            window.location.reload();
        }

    } catch (error) {
        console.error('Error polling import status:', error);
    }
}

// Function to start an import
async function startImport(uploadId) {
    try {
        const response = await fetch(`/admin/import/${uploadId}/start`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        // Start polling for status updates
        pollImportStatus(uploadId);

    } catch (error) {
        console.error('Error starting import:', error);
        alert('Failed to start import. Please try again.');
    }
}

// Start polling for any active imports when the page loads
document.addEventListener('DOMContentLoaded', () => {
    const activeImports = document.querySelectorAll('tr[data-upload-id]');
    activeImports.forEach(row => {
        const uploadId = row.dataset.uploadId;
        const status = row.querySelector('[id^="status-"]')?.textContent?.trim();

        if (status === 'Extracting' || status === 'Importing') {
            pollImportStatus(uploadId);
        }
    });
});
