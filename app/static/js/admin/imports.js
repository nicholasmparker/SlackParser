/**
 * Handles import functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    // Attach event listeners to import buttons
    attachImportButtonListeners();

    // Start polling if there are any imports in progress
    const hasActiveImports = document.querySelector('tr[data-upload-id]') !== null;
    if (hasActiveImports) {
        pollImportStatus();
    }
});

/**
 * Attach event listeners to import-related buttons
 */
function attachImportButtonListeners() {
    // Start import buttons
    document.querySelectorAll('.start-import-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const uploadId = this.getAttribute('data-upload-id');
            startImport(uploadId);
        });
    });

    // Cancel import buttons
    document.querySelectorAll('.cancel-import-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const uploadId = this.getAttribute('data-upload-id');
            cancelImport(uploadId);
        });
    });

    // Restart import buttons (dynamically added)
    document.addEventListener('click', function(e) {
        if (e.target.closest('.restart-import-btn')) {
            const btn = e.target.closest('.restart-import-btn');
            const uploadId = btn.getAttribute('data-upload-id');
            restartImport(uploadId);
        }
    });
}

/**
 * Poll for import status updates
 */
function pollImportStatus(uploadId) {
    console.log("Polling import status for upload ID:", uploadId);

    // Set up an interval to poll the status
    const pollInterval = setInterval(() => {
        fetch(`/admin/import-status/${uploadId}`)
            .then(response => response.json())
            .then(data => {
                console.log("Status update:", data);

                // Update the progress bar
                const progressBar = document.querySelector(`#upload-${uploadId} .progress-bar`);
                const progressText = document.querySelector(`#upload-${uploadId} .progress-text`);

                if (progressBar && progressText) {
                    const percent = data.progress_percent || 0;
                    progressBar.style.width = `${percent}%`;
                    progressBar.setAttribute('aria-valuenow', percent);
                    progressBar.textContent = `${percent}%`;
                    progressText.textContent = data.progress || 'Importing...';
                }

                // Check if the import is complete or failed
                if (data.status === "IMPORTED") {
                    console.log("Import completed");
                    clearInterval(pollInterval);

                    // Update the UI
                    const actionsContainer = document.querySelector(`#upload-${uploadId} .upload-actions`);
                    if (actionsContainer) {
                        actionsContainer.innerHTML = `
                            <div class="alert alert-success">
                                Import completed successfully
                            </div>
                        `;
                    }

                    // Refresh the page after a short delay
                    setTimeout(() => {
                        window.location.reload();
                    }, 3000);
                } else if (data.status === "ERROR") {
                    console.log("Import failed:", data.error);
                    clearInterval(pollInterval);

                    // Update the UI
                    const actionsContainer = document.querySelector(`#upload-${uploadId} .upload-actions`);
                    if (actionsContainer) {
                        actionsContainer.innerHTML = `
                            <div class="alert alert-danger">
                                Import failed: ${data.error || 'Unknown error'}
                            </div>
                            <button class="btn btn-warning" onclick="startImport('${uploadId}')">
                                <i class="fas fa-redo"></i> Retry Import
                            </button>
                        `;
                    }
                }
            })
            .catch(error => {
                console.error("Error polling status:", error);
                // Don't clear the interval, just log the error and continue polling
            });
    }, 2000); // Poll every 2 seconds

    // Store the interval ID in a global variable so we can clear it later
    window.pollIntervals = window.pollIntervals || {};
    window.pollIntervals[uploadId] = pollInterval;
}

/**
 * Start the import process for an upload
 */
function startImport(uploadId) {
    console.log("Starting import for upload ID:", uploadId);

    // Get the current status
    fetch(`/admin/import-status/${uploadId}`)
        .then(response => response.json())
        .then(data => {
            console.log("Current status:", data);

            if (data.status === "UPLOADED") {
                // Call the extract endpoint for extraction
                fetch(`/admin/extract/${uploadId}/start`, {
                    method: 'POST'
                })
                    .then(response => {
                        if (!response.ok) {
                            throw new Error(`HTTP error! Status: ${response.status}`);
                        }
                        return response.json();
                    })
                    .then(data => {
                        console.log("Extraction started:", data);

                        // Update the UI
                        const actionsContainer = document.querySelector(`#upload-${uploadId} .upload-actions`);
                        if (actionsContainer) {
                            actionsContainer.innerHTML = `
                                <div class="progress-container">
                                    <div class="progress">
                                        <div class="progress-bar" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">0%</div>
                                    </div>
                                    <div class="progress-text">Starting extraction...</div>
                                </div>
                            `;
                        }

                        // Start polling for status updates
                        pollImportStatus(uploadId);
                    })
                    .catch(error => {
                        console.error("Error starting extraction:", error);
                        showError(`Error starting extraction: ${error.message}`);
                    });
            } else if (data.status === "EXTRACTED") {
                // Call the start-import-process endpoint
                fetch(`/admin/import/${uploadId}/start`, {
                    method: 'POST'
                })
                    .then(async response => {
                        if (!response.ok) {
                            // Try to get the error message from the response
                            let errorText = "";
                            try {
                                const errorData = await response.json();
                                errorText = errorData.error || `HTTP error! Status: ${response.status}`;
                            } catch (e) {
                                errorText = `HTTP error! Status: ${response.status}`;
                            }
                            throw new Error(errorText);
                        }
                        return response.json();
                    })
                    .then(data => {
                        console.log("Import started:", data);

                        // Update the UI
                        const actionsContainer = document.querySelector(`#upload-${uploadId} .upload-actions`);
                        if (actionsContainer) {
                            actionsContainer.innerHTML = `
                                <div class="progress-container">
                                    <div class="progress">
                                        <div class="progress-bar" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">0%</div>
                                    </div>
                                    <div class="progress-text">Starting import...</div>
                                </div>
                            `;
                        }

                        // Start polling for status updates
                        pollImportStatus(uploadId);
                    })
                    .catch(error => {
                        console.error("Error starting import:", error);
                        showError(`Error starting import: ${error.message}`);
                    });
            } else if (data.status === "IMPORTING") {
                console.log("Import already in progress");
                // Start polling for status updates
                pollImportStatus(uploadId);
            } else if (data.status === "IMPORTED") {
                console.log("Import already completed");
                showMessage("Import already completed");
            } else if (data.status === "ERROR") {
                console.log("Import failed:", data.error);
                showError(`Import failed: ${data.error}`);
            } else if (data.status === "EXTRACTING") {
                console.log("Extraction in progress, cannot start import yet");
                showMessage("Extraction in progress, please wait");
            } else {
                console.log("Unknown status:", data.status);
                showError(`Unknown status: ${data.status}`);
            }
        })
        .catch(error => {
            console.error("Error getting status:", error);
            showError(`Error getting status: ${error.message}`);
        });
}

/**
 * Cancel an import
 */
function cancelImport(uploadId) {
    if (!confirm('Are you sure you want to cancel this import? This operation cannot be undone.')) {
        return;
    }

    // Update UI immediately
    UI.updateStatus(uploadId, 'Cancelling...', '', 0);

    // Disable the cancel button
    const cancelBtn = document.querySelector(`.cancel-import-btn[data-upload-id="${uploadId}"]`);
    if (cancelBtn) {
        cancelBtn.disabled = true;
        cancelBtn.classList.add('opacity-50', 'cursor-not-allowed');
    }

    // Send request to cancel import
    fetch(`/admin/cancel-import/${uploadId}`, {
        method: 'POST'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            UI.updateStatus(uploadId, 'Cancelled', '', 0);
            updateActions(uploadId, 'cancelled');
        } else {
            UI.updateStatus(uploadId, 'Error', data.error || 'Failed to cancel import', 0);

            // Re-enable the cancel button
            if (cancelBtn) {
                cancelBtn.disabled = false;
                cancelBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }
    })
    .catch(error => {
        console.error('Error cancelling import:', error);
        UI.updateStatus(uploadId, 'Error', error.message, 0);

        // Re-enable the cancel button
        if (cancelBtn) {
            cancelBtn.disabled = false;
            cancelBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    });
}

/**
 * Restart an import
 */
function restartImport(uploadId) {
    if (!confirm('Are you sure you want to restart this import?')) {
        return;
    }

    // Update UI immediately
    UI.updateStatus(uploadId, 'Restarting...', '', 0);

    // Disable the restart button
    const restartBtn = document.querySelector(`.restart-import-btn[data-upload-id="${uploadId}"]`);
    if (restartBtn) {
        restartBtn.disabled = true;
        restartBtn.classList.add('opacity-50', 'cursor-not-allowed');
    }

    // Send request to restart import
    fetch(`/admin/restart-import/${uploadId}`, {
        method: 'POST'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Start polling for progress
            pollImportStatus(uploadId);
        } else {
            UI.updateStatus(uploadId, 'Error', data.error || 'Failed to restart import', 0);

            // Re-enable the restart button
            if (restartBtn) {
                restartBtn.disabled = false;
                restartBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }
    })
    .catch(error => {
        console.error('Error restarting import:', error);
        UI.updateStatus(uploadId, 'Error', error.message, 0);

        // Re-enable the restart button
        if (restartBtn) {
            restartBtn.disabled = false;
            restartBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    });
}

/**
 * Update action buttons based on status
 */
function updateActions(uploadId, status) {
    const actionsCell = document.getElementById(`actions-cell-${uploadId}`);
    if (!actionsCell) return;

    // Convert status to lowercase for consistent comparison
    const statusLower = status.toLowerCase();

    // Clear existing buttons
    actionsCell.innerHTML = '';

    // Add appropriate buttons based on status
    if (['uploaded', 'error', 'extracted'].includes(statusLower)) {
        // Start button
        const startBtn = document.createElement('button');
        startBtn.className = 'start-import-btn text-[#1264a3] hover:text-[#0b4d82] transition-colors';
        startBtn.setAttribute('data-upload-id', uploadId);
        startBtn.innerHTML = `
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
        `;
        startBtn.addEventListener('click', function() {
            startImport(uploadId);
        });
        actionsCell.appendChild(startBtn);
    } else if (['extracting', 'importing', 'training'].includes(statusLower)) {
        // Cancel button
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'cancel-import-btn text-red-500 hover:text-red-400 transition-colors';
        cancelBtn.setAttribute('data-upload-id', uploadId);
        cancelBtn.innerHTML = `
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        `;
        cancelBtn.addEventListener('click', function() {
            cancelImport(uploadId);
        });
        actionsCell.appendChild(cancelBtn);
    } else if (['cancelled', 'canceled', 'completed'].includes(statusLower)) {
        // Restart button
        const restartBtn = document.createElement('button');
        restartBtn.className = 'restart-import-btn text-[#1264a3] hover:text-[#0b4d82] transition-colors';
        restartBtn.setAttribute('data-upload-id', uploadId);
        restartBtn.innerHTML = `
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
        `;
        restartBtn.addEventListener('click', function() {
            restartImport(uploadId);
        });
        actionsCell.appendChild(restartBtn);
    }
}

/**
 * Show an error message
 */
function showError(message) {
    const alertContainer = document.getElementById('alert-container');
    if (alertContainer) {
        alertContainer.innerHTML = `
            <div class="alert alert-danger alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
    } else {
        alert(message);
    }
}

/**
 * Show a success message
 */
function showMessage(message) {
    const alertContainer = document.getElementById('alert-container');
    if (alertContainer) {
        alertContainer.innerHTML = `
            <div class="alert alert-success alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
    } else {
        alert(message);
    }
}
