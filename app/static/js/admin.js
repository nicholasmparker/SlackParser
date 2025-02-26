// Function to restart an import
async function restartImport(uploadId) {
    try {
        const response = await fetch(`/api/restart_import/${uploadId}`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // Refresh the page to show updated status
        window.location.reload();
        
    } catch (error) {
        console.error('Error restarting import:', error);
        alert('Failed to restart import. Please try again.');
    }
}
