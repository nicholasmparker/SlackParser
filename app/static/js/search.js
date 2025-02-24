document.addEventListener('DOMContentLoaded', function() {
    const searchForm = document.getElementById('searchForm');
    const searchResults = document.getElementById('searchResults');
    const searchLoading = document.getElementById('searchLoading');
    const hybridAlpha = document.getElementById('hybrid_alpha');
    const hybridValue = document.getElementById('hybrid_value');
    
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
        searchForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            // Show loading state
            if (searchResults) searchResults.style.display = 'none';
            if (searchLoading) searchLoading.style.display = 'block';
            
            // Get form data
            const query = document.getElementById('query').value;
            const hybrid_alpha = document.getElementById('hybrid_alpha')?.value || 0.5;
            
            try {
                // Make search request
                const response = await fetch('/search', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        query: query,
                        hybrid_alpha: parseFloat(hybrid_alpha),
                        limit: 50
                    })
                });
                
                if (!response.ok) {
                    throw new Error('Search request failed');
                }
                
                const data = await response.json();
                
                // Clear previous results
                if (searchResults) {
                    searchResults.innerHTML = '';
                    
                    // Add results
                    if (data.results && data.results.length > 0) {
                        data.results.forEach(result => {
                            const resultHtml = `
                                <div class="card mb-3">
                                    <div class="card-body">
                                        <div class="d-flex justify-content-between align-items-start mb-3">
                                            <div class="d-flex gap-3">
                                                <div class="message-channel">
                                                    ${result.conversation?.type === 'channel' ? '#' : ''}${result.conversation?.name || 'Unknown'}
                                                </div>
                                                <div class="message-user text-muted">
                                                    ${result.user_name || result.user}
                                                </div>
                                                <div class="message-time text-muted">
                                                    ${new Date(result.ts * 1000).toLocaleString()}
                                                </div>
                                            </div>
                                            <a href="/conversation/${result.conversation_id}?ts=${result.ts}" 
                                               class="btn btn-outline-primary btn-sm">
                                                View in context
                                            </a>
                                        </div>
                                        <div class="message-text">${result.text}</div>
                                        ${result.score ? `
                                            <div class="mt-2 text-muted small">
                                                Relevance: ${Math.round(result.score * 100)}%
                                            </div>
                                        ` : ''}
                                    </div>
                                </div>
                            `;
                            searchResults.insertAdjacentHTML('beforeend', resultHtml);
                        });
                    } else {
                        searchResults.innerHTML = `
                            <div class="text-center py-5">
                                <h5>No results found</h5>
                                <p class="text-muted">Try adjusting your search query</p>
                            </div>
                        `;
                    }
                }
                
            } catch (error) {
                console.error('Search error:', error);
                if (searchResults) {
                    searchResults.innerHTML = `
                        <div class="alert alert-danger" role="alert">
                            <h5 class="alert-heading">Error</h5>
                            <p class="mb-0">${error.message}</p>
                        </div>
                    `;
                }
            } finally {
                // Hide loading state
                if (searchLoading) searchLoading.style.display = 'none';
                if (searchResults) searchResults.style.display = 'block';
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
