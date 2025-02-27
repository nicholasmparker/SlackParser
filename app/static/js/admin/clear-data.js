/**
 * Handles clear data functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    const clearCheckboxes = document.querySelectorAll('.clear-checkbox');
    const clearButton = document.getElementById('clearButton');
    const clearAllBtn = document.getElementById('clear-all-btn');

    // Handle clear all button
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', function() {
            if (confirm('Are you sure you want to clear ALL data? This action cannot be undone.')) {
                // Show loading indicator or disable button
                clearAllBtn.disabled = true;
                clearAllBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Clearing...';

                fetch('/admin/clear-all', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({}) // Send empty JSON object
                })
                    .then(response => {
                        if (!response.ok) {
                            throw new Error(`HTTP error! Status: ${response.status}`);
                        }
                        return response.json();
                    })
                    .then(data => {
                        if (data.status === 'success') {
                            // Success - reload without alert
                            window.location.reload();
                        } else {
                            alert('Error clearing data: ' + (data.message || 'Unknown error'));
                        }
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert('Error clearing data: ' + error.message);
                        // Re-enable button
                        clearAllBtn.disabled = false;
                        clearAllBtn.innerHTML = '<i class="fas fa-trash"></i> Clear All Data';
                    });
            }
        });
    }

    if (!clearCheckboxes.length || !clearButton) return;

    // Update clear button state based on checkbox selection
    function updateClearButton() {
        const anyChecked = Array.from(clearCheckboxes).some(cb => cb.checked);

        if (anyChecked) {
            clearButton.disabled = false;
            clearButton.classList.remove('opacity-50', 'cursor-not-allowed');
        } else {
            clearButton.disabled = true;
            clearButton.classList.add('opacity-50', 'cursor-not-allowed');
        }
    }

    // Add event listeners to checkboxes
    clearCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateClearButton);
    });

    // Initialize button state
    updateClearButton();
});
