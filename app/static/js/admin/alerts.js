/**
 * Handles alert messages in the admin interface
 */
document.addEventListener('DOMContentLoaded', function() {
    // Get URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const alertContainer = document.createElement('div');
    alertContainer.className = 'mb-4';

    // Check for cleared=true parameter
    if (urlParams.get('cleared') === 'true') {
        const successAlert = document.createElement('div');
        successAlert.className = 'bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded relative';
        successAlert.innerHTML = `
            <strong class="font-bold">Success!</strong>
            <span class="block sm:inline">Data has been cleared successfully.</span>
            <button type="button" class="absolute top-0 right-0 px-4 py-3" onclick="this.parentElement.remove()">
                <svg class="h-4 w-4 fill-current text-green-500" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
                    <path d="M14.348 14.849a1.2 1.2 0 0 1-1.697 0L10 11.819l-2.651 3.029a1.2 1.2 0 1 1-1.697-1.697l2.758-3.15-2.759-3.152a1.2 1.2 0 1 1 1.697-1.697L10 8.183l2.651-3.031a1.2 1.2 0 1 1 1.697 1.697l-2.758 3.152 2.758 3.15a1.2 1.2 0 0 1 0 1.698z"/>
                </svg>
            </button>
        `;
        alertContainer.appendChild(successAlert);

        // Remove the parameter from URL without refreshing
        const newUrl = window.location.pathname + window.location.search.replace('cleared=true', '').replace(/(\?|&)$/, '');
        window.history.replaceState({}, document.title, newUrl);
    }

    // Check for error parameter
    if (urlParams.get('error')) {
        const errorMessage = urlParams.get('message') || 'An error occurred.';
        const errorAlert = document.createElement('div');
        errorAlert.className = 'bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative';
        errorAlert.innerHTML = `
            <strong class="font-bold">Error!</strong>
            <span class="block sm:inline">${errorMessage}</span>
            <button type="button" class="absolute top-0 right-0 px-4 py-3" onclick="this.parentElement.remove()">
                <svg class="h-4 w-4 fill-current text-red-500" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
                    <path d="M14.348 14.849a1.2 1.2 0 0 1-1.697 0L10 11.819l-2.651 3.029a1.2 1.2 0 1 1-1.697-1.697l2.758-3.15-2.759-3.152a1.2 1.2 0 1 1 1.697-1.697L10 8.183l2.651-3.031a1.2 1.2 0 1 1 1.697 1.697l-2.758 3.152 2.758 3.15a1.2 1.2 0 0 1 0 1.698z"/>
                </svg>
            </button>
        `;
        alertContainer.appendChild(errorAlert);

        // Remove the parameters from URL without refreshing
        const newUrl = window.location.pathname + window.location.search.replace(/[?&]error=[^&]*/, '').replace(/[?&]message=[^&]*/, '').replace(/(\?|&)$/, '');
        window.history.replaceState({}, document.title, newUrl);
    }

    // Insert the alert container after the dashboard title
    if (alertContainer.children.length > 0) {
        const dashboardTitle = document.querySelector('.max-w-7xl h1');
        if (dashboardTitle) {
            const titleContainer = dashboardTitle.closest('div');
            if (titleContainer && titleContainer.parentElement) {
                titleContainer.parentElement.insertBefore(alertContainer, titleContainer.nextElementSibling);
            }
        }
    }
});
