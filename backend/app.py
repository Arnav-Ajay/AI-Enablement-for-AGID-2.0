from flask import Flask, request, jsonify
from openai import OpenAI
import pandas as pd
from flask_cors import CORS
import json
import os
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Load your cleaned data and metadata
DATA_PATH = r'src\data\title_iii_cleaned.csv'
df = pd.read_csv(DATA_PATH)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

def add_bootstrap_table_classes(table_html):
    import re
    # Add Bootstrap classes to the <table> tag
    return re.sub(r'<table([^>]*)>', r'<table\1 class="table table-bordered table-striped table-hover">', table_html, count=1)


@app.route('/query', methods=['POST'])
def query():
    user_query = request.json.get('query', '')
    if not user_query:
        return jsonify({"error": "No query provided."}), 400

    try:
        # 1. Call LLM to translate query to filter JSON
        # ...existing code...
        prompt = (
            "Given the following user request for the AGID Title III dataset, "
            "output a valid JSON object with these keys: years (list of integers), "
            "geography (list of strings), metrics (list of strings). "
            "Only output the JSON. User request: '" + user_query + "'"
        )
        llm_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a data assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150
        )
        filter_json = llm_response.choices[0].message.content

        import re
        print("LLM raw response:", filter_json)  # Debug print
        filter_json = re.sub(r"^```json|```$", "", filter_json.strip(), flags=re.MULTILINE)

        try:
            filters = json.loads(filter_json)
        except json.JSONDecodeError:
            return jsonify({"error": "Could not parse filter from LLM response."}), 500
        # ...existing code...
        
        # Ensure filters are always lists
        for key in ['years', 'geography', 'metrics']:
            if key in filters and not isinstance(filters[key], list):
                filters[key] = [filters[key]]
        # 2. Filter the DataFrame
        try:
            filtered = df[
                (df['Year'].isin(filters['years'])) &
                (df['Geography'].isin(filters['geography'])) &
                (df['Category'].isin(filters['metrics']))
            ]
        except Exception as e:
            return jsonify({"error": f"Error filtering data: {str(e)}"}), 500

        if filtered.empty:
            return jsonify({"error": "No data found for your query."}), 404

        # 3. Generate summary with LLM
        table_sample = filtered.head(10).to_markdown(index=False)
        summary_prompt = f"Summarize the following table for a non-technical user:\n{table_sample}"

        try:
            summary_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a data assistant."},
                    {"role": "user", "content": summary_prompt}
                ],
                max_tokens=100
            )
            summary = summary_response.choices[0].message.content
        except Exception as e:
            summary = "Could not generate summary due to an error."

        # 4. Return HTML table and summary
        table_html = filtered.head(10).to_html(index=False)
        table_html = add_bootstrap_table_classes(table_html)
        return jsonify({
            "summary": summary,
            "table_html": table_html
        })
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
