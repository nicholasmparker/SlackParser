document.addEventListener('DOMContentLoaded', function() {
    console.log('Search JS loaded');
    const searchForm = document.getElementById('searchForm');
    const searchResults = document.getElementById('searchResults');
    const hybridAlpha = document.getElementById('hybrid_alpha');
    const hybridValue = document.getElementById('hybrid_value');

    // Create a simple loading indicator
    const loadingIndicator = document.createElement('div');
    loadingIndicator.id = 'simple-loading';
    loadingIndicator.innerHTML = `
        <div class="bg-[#222529] rounded-lg p-6 mb-6 border border-gray-700">
            <div class="text-center">
                <p class="text-gray-100 text-lg">Searching messages... Please wait.</p>
            </div>
        </div>
    `;
    loadingIndicator.style.display = 'none';

    // Insert the loading indicator before search results
    if (searchResults && searchResults.parentNode) {
        searchResults.parentNode.insertBefore(loadingIndicator, searchResults);
    }

    console.log('Form element:', searchForm);

    if (hybridAlpha) {
        // Update hybrid search balance value
        hybridAlpha.addEventListener('input', function(e) {
            const value = e.target.value;
            const percent = Math.round(value * 100);
            hybridValue.textContent = `${100 - percent}% Keyword / ${percent}% AI`;
        });

        // Trigger initial update
        hybridAlpha.dispatchEvent(new Event('input'));
    }

    if (searchForm) {
        console.log('Adding submit handler');
        searchForm.addEventListener('submit', async function(e) {
            console.log('Form submitted');
            e.preventDefault();
            e.stopPropagation();

            // Show loading indicator
            loadingIndicator.style.display = 'block';

            // Hide results while loading
            if (searchResults) {
                searchResults.style.display = 'none';
            }

            // Get form data
            const query = document.getElementById('query').value;
            const hybrid_alpha = hybridAlpha ? hybridAlpha.value : 0.5;

            try {
                // Perform search
                const response = await fetch('/api/v1/search', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        query: query,
                        hybrid_alpha: parseFloat(hybrid_alpha),
                        limit: 50
                    })
                });

                if (!response.ok) {
                    throw new Error(`Search failed: ${response.status} ${response.statusText}`);
                }

                const data = await response.json();

                console.log('Search results:', data.results);

                // Hide loading indicator
                loadingIndicator.style.display = 'none';

                // Show search results
                if (searchResults) {
                    searchResults.style.display = 'block';
                }

                // Clear previous results
                if (searchResults) {
                    searchResults.innerHTML = '';
                }

                // Display results
                if (data.results && data.results.length > 0) {
                    data.results.forEach(result => {
                        const resultElement = document.createElement('div');
                        resultElement.className = 'bg-[#222529] rounded-lg p-4 mb-4 border border-gray-700 hover:border-gray-600 transition-all';

                        const formattedDate = formatTimestamp(result.timestamp || result.ts);
                        const username = result.username || result.user || 'Unknown User';

                        resultElement.innerHTML = `
                            <div class="flex justify-between items-start mb-3">
                                <div class="flex gap-4 text-sm">
                                    <span class="text-gray-400">${result.conversation.name}</span>
                                    <span class="text-gray-400">|</span>
                                    <span class="text-gray-400">${username}</span>
                                </div>
                                <div class="text-gray-500 text-sm">${formattedDate}</div>
                            </div>
                            <div class="text-gray-100">${result.text}</div>
                        `;

                        searchResults.appendChild(resultElement);
                    });
                } else {
                    searchResults.innerHTML = `
                        <div class="bg-[#222529] rounded-lg p-6 border border-gray-700">
                            <p class="text-gray-400 text-center">No results found for "${data.query}"</p>
                        </div>
                    `;
                }

            } catch (error) {
                console.error('Search error:', error);

                // Hide loading indicator
                loadingIndicator.style.display = 'none';

                // Show error message
                if (searchResults) {
                    searchResults.innerHTML = `
                        <div class="bg-[#222529] rounded-lg p-6 border border-gray-700">
                            <p class="text-red-400 text-center">Error: ${error.message || 'Unknown error'}</p>
                        </div>
                    `;
                    searchResults.style.display = 'block';
                }
            }
        });

        // If there's an initial query, trigger search
        const urlParams = new URLSearchParams(window.location.search);
        const initialQuery = urlParams.get('q');
        if (initialQuery) {
            document.getElementById('query').value = initialQuery;
            searchForm.dispatchEvent(new Event('submit'));
        }
    }
});

function formatTimestamp(timestamp) {
    if (!timestamp) return 'Unknown date';

    // Handle numeric timestamps (Unix epoch in seconds)
    if (typeof timestamp === 'number') {
        const date = new Date(timestamp * 1000);
        return date.toLocaleString();
    }

    // Handle string timestamps
    try {
        const date = new Date(timestamp);
        if (!isNaN(date.getTime())) {
            return date.toLocaleString();
        }
    } catch (e) {
        console.error('Error formatting timestamp:', e);
    }

    return 'Invalid date';
}
