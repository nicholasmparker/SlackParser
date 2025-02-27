/**
 * Handles file upload functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    const uploadForm = document.getElementById('uploadForm');
    const uploadButton = document.getElementById('uploadButton');
    const uploadProgress = document.getElementById('uploadProgress');
    const uploadStatus = document.getElementById('uploadStatus');
    const uploadProgressBar = document.getElementById('uploadProgressBar');
    const uploadProgressPercent = document.getElementById('uploadProgressPercent');
    const uploadProgressBytes = document.getElementById('uploadProgressBytes');
    const uploadTotalBytes = document.getElementById('uploadTotalBytes');

    if (!uploadForm) return;

    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();

        const fileInput = document.getElementById('file');
        const file = fileInput.files[0];

        if (!file) {
            alert('Please select a file to upload');
            return;
        }

        // Show progress bar
        uploadProgress.classList.remove('hidden');
        uploadButton.disabled = true;
        uploadButton.classList.add('opacity-50', 'cursor-not-allowed');

        // Create XMLHttpRequest
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/admin/upload', true);

        // Track upload progress
        xhr.upload.onprogress = function(e) {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                uploadProgressBar.style.width = percent + '%';
                uploadProgressPercent.textContent = percent + '%';
                uploadProgressBytes.textContent = formatBytes(e.loaded);
                uploadTotalBytes.textContent = formatBytes(e.total);
            }
        };

        // Handle response state changes
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 200) {
                    try {
                        const response = JSON.parse(xhr.responseText);
                        uploadStatus.textContent = 'Upload complete!';
                        uploadStatus.classList.remove('text-[#1264a3]');
                        uploadStatus.classList.add('text-green-500');

                        // Reload the page after a short delay to show the new upload
                        setTimeout(function() {
                            window.location.reload();
                        }, 1000);
                    } catch (e) {
                        console.error('Error parsing response:', e);
                        uploadStatus.textContent = 'Error: Invalid response from server';
                        uploadStatus.classList.remove('text-[#1264a3]');
                        uploadStatus.classList.add('text-red-500');
                    }
                } else {
                    uploadStatus.textContent = 'Error: ' + xhr.status;
                    uploadStatus.classList.remove('text-[#1264a3]');
                    uploadStatus.classList.add('text-red-500');
                }
            }
        };

        // Send the file
        const formData = new FormData();
        formData.append('file', file);
        xhr.send(formData);
    });

    /**
     * Format bytes to human-readable format
     */
    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 B';

        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];

        const i = Math.floor(Math.log(bytes) / Math.log(k));

        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }
});
