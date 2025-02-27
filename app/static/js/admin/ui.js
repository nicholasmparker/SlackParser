/**
 * UI utilities for the admin page
 */
const UI = {
    /**
     * Update the status of an upload
     */
    updateStatus(uploadId, status, progress = '', progressPercent = 0, errorMessage = '') {
        const statusCell = document.getElementById(`status-cell-${uploadId}`);
        if (!statusCell) return;

        let statusHtml = '';
        let statusClass = '';
        
        // Normalize status to lowercase for consistent comparison
        const statusLower = status.toLowerCase();

        // Determine status class and HTML based on status
        switch (statusLower) {
            case 'extracting':
                statusClass = 'bg-blue-900/50 text-blue-100';
                statusHtml = `
                    <div class="space-y-2">
                        <span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Extracting</span>
                        <div id="progress-text-${uploadId}" class="text-sm text-gray-400 mt-1">${progress}</div>
                        <div class="w-full bg-[#1A1D21] rounded-full h-2 overflow-hidden">
                            <div id="progress-bar-${uploadId}" class="bg-[#1264a3] h-2 rounded-full" style="width: ${progressPercent}%"></div>
                        </div>
                    </div>
                `;
                break;

            case 'importing':
                statusClass = 'bg-blue-900/50 text-blue-100';
                statusHtml = `
                    <div class="space-y-2">
                        <span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Importing</span>
                        <div id="progress-text-${uploadId}" class="text-sm text-gray-400 mt-1">${progress}</div>
                        <div class="w-full bg-[#1A1D21] rounded-full h-2 overflow-hidden">
                            <div id="progress-bar-${uploadId}" class="bg-[#1264a3] h-2 rounded-full" style="width: ${progressPercent}%"></div>
                        </div>
                    </div>
                `;
                break;

            case 'training':
                statusClass = 'bg-purple-900/50 text-purple-100';
                statusHtml = `
                    <div class="space-y-2">
                        <span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Training</span>
                        <div id="progress-text-${uploadId}" class="text-sm text-gray-400 mt-1">${progress}</div>
                        <div class="w-full bg-[#1A1D21] rounded-full h-2 overflow-hidden">
                            <div id="progress-bar-${uploadId}" class="bg-purple-500 h-2 rounded-full" style="width: ${progressPercent}%"></div>
                        </div>
                    </div>
                `;
                break;

            case 'complete':
                statusClass = 'bg-green-900/50 text-green-100';
                statusHtml = `<span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Complete</span>`;
                break;

            case 'error':
                statusClass = 'bg-red-900/50 text-red-100';
                statusHtml = `
                    <div>
                        <span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Error</span>
                        ${errorMessage ? `<div id="error-message-${uploadId}" class="text-sm text-red-400 mt-1">${errorMessage}</div>` : ''}
                    </div>
                `;
                break;

            case 'uploaded':
                statusClass = 'bg-gray-700 text-gray-100';
                statusHtml = `<span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Uploaded</span>`;
                break;

            case 'extracted':
                statusClass = 'bg-yellow-900/50 text-yellow-100';
                statusHtml = `<span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Extracted</span>`;
                break;

            case 'cancelled':
            case 'canceled':
                statusClass = 'bg-gray-700 text-gray-100';
                statusHtml = `<span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">Cancelled</span>`;
                break;

            default:
                statusClass = 'bg-gray-700 text-gray-100';
                statusHtml = `<span id="status-${uploadId}" class="${statusClass} px-2 py-1 rounded-full text-xs">${status}</span>`;
        }

        // Update the status cell
        statusCell.innerHTML = statusHtml;
        
        // Update the actions based on the status
        updateActions(uploadId, status);
    }
};
