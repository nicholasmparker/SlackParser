/**
 * Main admin page script
 */
document.addEventListener('DOMContentLoaded', function() {
    // Initialize tabs if they exist
    initTabs();

    // Add debug button if in development
    addDebugButton();
});

/**
 * Initialize tabs functionality
 */
function initTabs() {
    const tabButtons = document.querySelectorAll('[data-tab]');
    const tabContents = document.querySelectorAll('[data-tab-content]');

    if (!tabButtons.length || !tabContents.length) return;

    // Show the first tab by default
    showTab(tabButtons[0].getAttribute('data-tab'));

    // Add click event listeners to tab buttons
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            showTab(tabName);

            // Update active tab in URL hash
            window.location.hash = tabName;
        });
    });

    // Check if there's a tab in the URL hash
    if (window.location.hash) {
        const tabName = window.location.hash.substring(1);
        const tabButton = document.querySelector(`[data-tab="${tabName}"]`);

        if (tabButton) {
            showTab(tabName);
        }
    }

    /**
     * Show a specific tab and hide others
     */
    function showTab(tabName) {
        // Hide all tab contents
        tabContents.forEach(content => {
            content.classList.add('hidden');
        });

        // Remove active class from all tab buttons
        tabButtons.forEach(button => {
            button.classList.remove('tab-active');
            button.classList.add('tab-inactive');
        });

        // Show the selected tab content
        const selectedContent = document.querySelector(`[data-tab-content="${tabName}"]`);
        if (selectedContent) {
            selectedContent.classList.remove('hidden');
        }

        // Add active class to the selected tab button
        const selectedButton = document.querySelector(`[data-tab="${tabName}"]`);
        if (selectedButton) {
            selectedButton.classList.remove('tab-inactive');
            selectedButton.classList.add('tab-active');
        }
    }
}

/**
 * Add debug button for development
 */
function addDebugButton() {
    const adminHeader = document.querySelector('h1');
    if (!adminHeader) return;

    const debugButton = document.createElement('button');
    debugButton.className = 'ml-4 text-xs text-gray-500 hover:text-gray-400';
    debugButton.textContent = 'Debug UI';
    debugButton.addEventListener('click', debugUI);

    adminHeader.appendChild(debugButton);
}

/**
 * Debug UI function
 */
function debugUI() {
    // Create a modal for debugging
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-[#222529] rounded-lg p-6 max-w-3xl w-full max-h-[80vh] overflow-y-auto">
            <h2 class="text-lg font-medium text-gray-100 mb-4">Debug UI</h2>

            <div class="space-y-4">
                <div>
                    <h3 class="text-md font-medium text-gray-100 mb-2">Test Status Updates</h3>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label class="block text-gray-400 mb-1">Upload ID</label>
                            <input type="text" id="debug-upload-id" class="w-full bg-[#1A1D21] text-gray-100 rounded border border-gray-700 px-3 py-2">
                        </div>
                        <div>
                            <label class="block text-gray-400 mb-1">Status</label>
                            <select id="debug-status" class="w-full bg-[#1A1D21] text-gray-100 rounded border border-gray-700 px-3 py-2">
                                <option value="extracting">Extracting</option>
                                <option value="importing">Importing</option>
                                <option value="training">Training</option>
                                <option value="complete">Complete</option>
                                <option value="error">Error</option>
                                <option value="uploaded">Uploaded</option>
                                <option value="extracted">Extracted</option>
                                <option value="cancelled">Cancelled</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-gray-400 mb-1">Progress</label>
                            <input type="text" id="debug-progress" class="w-full bg-[#1A1D21] text-gray-100 rounded border border-gray-700 px-3 py-2" value="Processing files...">
                        </div>
                        <div>
                            <label class="block text-gray-400 mb-1">Progress Percent</label>
                            <input type="number" id="debug-progress-percent" class="w-full bg-[#1A1D21] text-gray-100 rounded border border-gray-700 px-3 py-2" value="50" min="0" max="100">
                        </div>
                        <div class="md:col-span-2">
                            <label class="block text-gray-400 mb-1">Error Message</label>
                            <input type="text" id="debug-error-message" class="w-full bg-[#1A1D21] text-gray-100 rounded border border-gray-700 px-3 py-2" value="An error occurred during import">
                        </div>
                    </div>
                    <button id="debug-update-status" class="mt-4 bg-[#1264a3] hover:bg-[#0b4d82] text-white px-4 py-2 rounded transition-colors">
                        Update Status
                    </button>
                </div>

                <div>
                    <h3 class="text-md font-medium text-gray-100 mb-2">Force Update All Uploads</h3>
                    <button id="debug-force-update" class="bg-[#1264a3] hover:bg-[#0b4d82] text-white px-4 py-2 rounded transition-colors">
                        Force Update All
                    </button>
                </div>
            </div>

            <div class="mt-6 flex justify-end">
                <button id="debug-close" class="text-gray-400 hover:text-gray-300 transition-colors">
                    Close
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Add event listeners
    document.getElementById('debug-close').addEventListener('click', function() {
        document.body.removeChild(modal);
    });

    document.getElementById('debug-update-status').addEventListener('click', function() {
        const uploadId = document.getElementById('debug-upload-id').value;
        const status = document.getElementById('debug-status').value;
        const progress = document.getElementById('debug-progress').value;
        const progressPercent = document.getElementById('debug-progress-percent').value;
        const errorMessage = document.getElementById('debug-error-message').value;

        if (!uploadId) {
            alert('Please enter an Upload ID');
            return;
        }

        UI.updateStatus(uploadId, status, progress, progressPercent, errorMessage);
        updateActions(uploadId, status);
    });

    document.getElementById('debug-force-update').addEventListener('click', function() {
        forceUpdateAllUploads();
    });
}

/**
 * Force update all uploads
 */
function forceUpdateAllUploads() {
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
        })
        .catch(error => {
            console.error('Error forcing update:', error);
            alert('Error forcing update: ' + error.message);
        });
}
