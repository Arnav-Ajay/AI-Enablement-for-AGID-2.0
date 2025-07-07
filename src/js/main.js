document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('nl-query-form');
    if (form) {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            const query = document.getElementById('nl-query').value;
            document.getElementById('query-result').innerHTML =
                `<div class="alert alert-info">Processing your query...</div>`;

            try {
                const response = await fetch('http://localhost:5000/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query })
                });
                const data = await response.json();
                if (data.error) {
                    document.getElementById('query-result').innerHTML =
                        `<div class="alert alert-danger">${data.error}</div>`;
                } else {
                    document.getElementById('query-result').innerHTML =
                        `<div class="alert alert-success"><strong>Summary:</strong> ${data.summary}</div>
                         <div class="mt-3"><strong>Table:</strong><br>${data.table_html}</div>`;
                }
            } catch (err) {
                document.getElementById('query-result').innerHTML =
                    `<div class="alert alert-danger">Error: ${err.message}</div>`;
            }
        });
    }
});