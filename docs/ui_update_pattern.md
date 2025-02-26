# UI Update Pattern for Slack Import Process

## Overview

This document outlines the pattern used for updating the UI during the Slack import process. The approach ensures consistent UI updates across different states of the import process without requiring page reloads.

## Key Principles

1. **Consistent HTML Structure**: Maintain the same HTML structure for each state to avoid DOM manipulation issues
2. **Centralized Templates**: Use predefined templates for each UI state to ensure consistency
3. **Helper Functions**: Provide helper functions to abstract the UI update logic
4. **State Management**: Track the current state and update the UI accordingly
5. **Polling with Cleanup**: Properly manage polling intervals to avoid memory leaks

## UI States

The import process has the following states, each with its own UI representation:

| State | Description | UI Elements |
|-------|-------------|------------|
| `UPLOADED` | File uploaded but import not started | Status badge, Start Import button, Delete button |
| `STARTING` | Import process is being initiated | Status badge, progress text, disabled button |
| `EXTRACTING` | ZIP file is being extracted | Status badge, progress bar, progress text, Cancel button |
| `IMPORTING` | Data is being imported into the database | Status badge, progress bar, progress text, Cancel button |
| `EMBEDDING` | Embeddings are being generated | Status badge, progress bar, progress text, Cancel button |
| `COMPLETE` | Import process completed successfully | Status badge, View button, Delete button |
| `ERROR` | Error occurred during import | Status badge, error message, Restart button, Delete button |
| `CANCELLED` | Import was cancelled by user | Same as `UPLOADED` with additional message |

## Implementation

### UI Helper Object

The UI helper object provides templates and functions for updating the UI:

```javascript
const UI = {
    // Status cell templates for different states
    statusTemplates: {
        uploaded: (uploadId) => `...`,
        starting: (uploadId) => `...`,
        extracting: (uploadId, progress, progressPercent) => `...`,
        // ... other templates
    },
    
    // Action cell templates for different states
    actionTemplates: {
        uploaded: (uploadId) => `...`,
        processing: (uploadId) => `...`,
        // ... other templates
    },
    
    // Helper function to update the status cell
    updateStatus: function(uploadId, status, progress, progressPercent, errorMessage) {
        // Find the row and status cell
        // Update with appropriate template based on status
    },
    
    // Helper function to update the actions cell
    updateActions: function(uploadId, status) {
        // Find the row and actions cell
        // Update with appropriate template based on status
    },
    
    // Helper function to update both status and actions
    update: function(uploadId, status, progress, progressPercent, errorMessage) {
        this.updateStatus(uploadId, status, progress, progressPercent, errorMessage);
        this.updateActions(uploadId, status);
    }
};
```

### Polling for Updates

A polling mechanism checks for status updates and updates the UI accordingly:

```javascript
// Store polling intervals by upload ID
window.pollIntervals = window.pollIntervals || {};

function pollProgress(uploadId) {
    // Clear any existing interval for this upload
    if (window.pollIntervals[uploadId]) {
        clearInterval(window.pollIntervals[uploadId]);
    }
    
    // Create a new interval and store it
    window.pollIntervals[uploadId] = setInterval(() => {
        fetch(`/admin/import/${uploadId}/status`)
        .then(response => response.json())
        .then(data => {
            // Update UI based on status
            UI.update(
                uploadId, 
                data.status, 
                data.progress || '', 
                data.progress_percent || 0, 
                data.error || ''
            );
            
            // Stop polling if complete, error, or cancelled
            if (data.status === 'COMPLETE' || data.status === 'ERROR' || data.status === 'UPLOADED') {
                clearInterval(window.pollIntervals[uploadId]);
                delete window.pollIntervals[uploadId];
            }
        })
        .catch(error => {
            console.error('Error polling progress:', error);
            clearInterval(window.pollIntervals[uploadId]);
            delete window.pollIntervals[uploadId];
        });
    }, 1000); // Poll every second
}
```

### Starting an Import

The `startImport` function initiates the import process and updates the UI:

```javascript
function startImport(uploadId) {
    // Update UI to show starting state
    UI.update(uploadId, 'STARTING');
    
    fetch(`/admin/import/${uploadId}/start`, {
        method: 'POST'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Failed to start import');
        }
        return response.json().catch(() => ({ status: 'ok' }));
    })
    .then(data => {
        // Update UI to show extracting state
        UI.update(uploadId, 'EXTRACTING', 'Extracting ZIP file...', 0);
        
        // Start polling for progress
        pollProgress(uploadId);
    })
    .catch(error => {
        console.error('Error:', error);
        
        // Restore UI to previous state
        UI.update(uploadId, 'UPLOADED');
        
        alert('Failed to start import: ' + error.message);
    });
}
```

### Cancelling an Import

The `cancelImport` function cancels the import process and updates the UI:

```javascript
function cancelImport(uploadId) {
    if (!confirm('Are you sure you want to cancel this import?')) {
        return;
    }

    fetch(`/admin/import/${uploadId}/cancel`, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update UI to reflect cancelled state
            UI.update(uploadId, 'CANCELLED');
            
            // Stop any ongoing polling
            clearInterval(window.pollIntervals[uploadId]);
            delete window.pollIntervals[uploadId];
        } else {
            alert('Failed to cancel import');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to cancel import: ' + error.message);
    });
}
```

## Best Practices

1. **Always use the UI helper**: Use the UI helper functions for all UI updates to maintain consistency
2. **Clear polling intervals**: Always clear polling intervals when they are no longer needed
3. **Handle errors gracefully**: Provide meaningful error messages and restore the UI to a valid state
4. **Immediate feedback**: Update the UI immediately when an action is initiated, don't wait for the server response
5. **Consistent status representation**: Use the same visual representation for each status across the application

## Implementation Notes

- The UI helper object is defined at the top of the JavaScript code to ensure it's available to all functions
- Polling intervals are stored in a global object to allow for proper cleanup
- The UI is updated immediately when an action is initiated, then updated again based on the server response
- Error handling restores the UI to a valid state and provides meaningful error messages
