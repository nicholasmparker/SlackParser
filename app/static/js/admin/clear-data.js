/**
 * Handles clear data functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    const clearCheckboxes = document.querySelectorAll('.clear-checkbox');
    const clearButton = document.getElementById('clearButton');

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
    clearCheckboxes.forEach(cb => {
        cb.addEventListener('change', updateClearButton);
    });

    // Add confirmation to form submission
    const clearDataForm = document.getElementById('clearDataForm');
    if (clearDataForm) {
        clearDataForm.addEventListener('submit', function(e) {
            const checkedItems = Array.from(clearCheckboxes)
                .filter(cb => cb.checked)
                .map(cb => cb.id.replace('clear', ''))
                .join(', ');

            if (!confirm(`Are you sure you want to clear the following data: ${checkedItems}? This action cannot be undone.`)) {
                e.preventDefault();
            }
        });
    }
});
