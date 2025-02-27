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
function pollImportStatus() {
    fetch('/admin/import-status')
        .then(response => response.json())
        .then(data => {
            for (const uploadId in data) {
                UI.updateStatus(
                    uploadId,
                    data[uploadId].status,
                    data[uploadId].progress,
                    data[uploadId].progress_percent,
                    data[uploadId].error_message
                );
                updateActions(uploadId, data[uploadId].status);
            }

            // Continue polling if there are active imports
            const hasActiveImports = Object.values(data).some(item =>
                ['extracting', 'importing', 'training'].includes(item.status.toLowerCase())
            );

            if (hasActiveImports) {
                setTimeout(pollImportStatus, 2000);
            }
        })
        .catch(error => {
            console.error('Error polling import status:', error);
            setTimeout(pollImportStatus, 5000); // Retry after longer delay on error
        });
}

/**
 * Start an import
 */
function startImport(uploadId) {
    // Update UI immediately
    UI.updateStatus(uploadId, 'Starting...', '', 0);

    // Disable the start button
    const startBtn = document.querySelector(`.start-import-btn[data-upload-id="${uploadId}"]`);
    if (startBtn) {
        startBtn.disabled = true;
        startBtn.classList.add('opacity-50', 'cursor-not-allowed');
    }

    // Send request to start import
    fetch(`/admin/start-import/${uploadId}`, {
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
            pollProgress(uploadId);
        } else {
            UI.updateStatus(uploadId, 'Error', data.error || 'Failed to start import', 0);

            // Re-enable the start button
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }
    })
    .catch(error => {
        console.error('Error starting import:', error);
        UI.updateStatus(uploadId, 'Error', error.message, 0);

        // Re-enable the start button
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    });
}

/**
 * Poll for import progress
 */
function pollProgress(uploadId) {
    // Use the general import-status endpoint that we know works
    fetch('/admin/import-status')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            // Check if this upload is in the data
            if (data[uploadId]) {
                // Update UI with progress
                UI.updateStatus(
                    uploadId,
                    data[uploadId].status,
                    data[uploadId].progress,
                    data[uploadId].progress_percent,
                    data[uploadId].error_message
                );

                // Update action buttons
                updateActions(uploadId, data[uploadId].status);
                
                // Continue polling if import is still in progress
                if (['extracting', 'importing', 'training'].includes(data[uploadId].status.toLowerCase())) {
                    setTimeout(() => pollProgress(uploadId), 2000);
                } else if (data[uploadId].status.toLowerCase() === 'complete') {
                    // If training is complete, stop polling
                    console.log('Import and training complete');
                } else if (data[uploadId].status.toLowerCase() === 'extracted') {
                    // If extraction is complete but import hasn't started yet, poll less frequently
                    setTimeout(() => pollProgress(uploadId), 5000);
                }
            } else {
                // Upload not found in data, retry after delay
                console.warn(`Upload ${uploadId} not found in import status data`);
                setTimeout(() => pollProgress(uploadId), 2000);
            }
        })
        .catch(error => {
            console.error('Error polling progress:', error);
            // On error, continue polling but with a longer delay
            setTimeout(() => pollProgress(uploadId), 5000);
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
            pollProgress(uploadId);
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

    // Clear existing buttons
    actionsCell.innerHTML = '';

    // Add appropriate buttons based on status
    if (['uploaded', 'error', 'extracted'].includes(status.toLowerCase())) {
        // Start button
        const startBtn = document.createElement('button');
        startBtn.className = 'start-import-btn text-[#1264a3] hover:text-[#0b4d82] transition-colors';
        startBtn.setAttribute('data-upload-id', uploadId);
        startBtn.innerHTML = `
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
        `;
        startBtn.addEventListener('click', function() {
            startImport(uploadId);
        });
        actionsCell.appendChild(startBtn);
    } else if (['extracting', 'importing', 'training'].includes(status.toLowerCase())) {
        // Cancel button
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'cancel-import-btn text-red-500 hover:text-red-400 transition-colors';
        cancelBtn.setAttribute('data-upload-id', uploadId);
        cancelBtn.innerHTML = `
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        `;
        cancelBtn.addEventListener('click', function() {
            cancelImport(uploadId);
        });
        actionsCell.appendChild(cancelBtn);
    } else if (['cancelled', 'error'].includes(status.toLowerCase())) {
        // Restart button
        const restartBtn = document.createElement('button');
        restartBtn.className = 'restart-import-btn text-[#1264a3] hover:text-[#0b4d82] transition-colors';
        restartBtn.setAttribute('data-upload-id', uploadId);
        restartBtn.innerHTML = `
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
        `;
        restartBtn.addEventListener('click', function() {
            restartImport(uploadId);
        });
        actionsCell.appendChild(restartBtn);
    }
}
