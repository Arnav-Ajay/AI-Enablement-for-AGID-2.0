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
METADATA_PATH = r'src\data\metadata_filter_tree.json'
df = pd.read_csv(DATA_PATH)

# Load metadata and build mapping
with open(METADATA_PATH, 'r', encoding='utf-8') as f:
    metadata = json.load(f)

def extract_attribute_to_displaytext(metadata):
    """Recursively extract mapping from Attribute_Name to Display_Text."""
    mapping = {}
    def recurse(obj):
        if isinstance(obj, dict):
            if "Attribute_Name" in obj and "Display_Text" in obj:
                mapping[obj["Attribute_Name"]] = obj["Display_Text"]
            for v in obj.values():
                recurse(v)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)
    recurse(metadata)
    return mapping

attribute_to_displaytext = extract_attribute_to_displaytext(metadata)

def extract_attribute_mappings(metadata):
    """Recursively extract mappings from Display_Text/Data_Element to Attribute_Name."""
    mappings = {}
    def recurse(obj):
        if isinstance(obj, dict):
            if "Attribute_Name" in obj:
                # Map both Display_Text and Data_Element to Attribute_Name
                if "Display_Text" in obj and obj["Display_Text"]:
                    mappings[obj["Display_Text"].strip()] = obj["Attribute_Name"]
                if "Data_Element" in obj and obj["Data_Element"]:
                    mappings[obj["Data_Element"].strip()] = obj["Attribute_Name"]
            for v in obj.values():
                recurse(v)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)
    recurse(metadata)
    return mappings

attribute_mappings = extract_attribute_mappings(metadata)

def map_metric_to_attributes(metric):
    """Return all Attribute_Names that partially match the metric."""
    matches = []
    for k, v in attribute_mappings.items():
        if metric.lower() in k.lower():
            matches.append(v)
    return matches


# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

def add_bootstrap_table_classes(table_html):
    return table_html.replace(
        'class="dataframe"',
        'class="table table-striped table-bordered"'
    )

@app.route('/query', methods=['POST'])
def query():
    user_query = request.json.get('query', '')
    if not user_query:
        return jsonify({"error": "No query provided."}), 400

    try:
        # 1. Call LLM to translate query to filter JSON
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
        
        # Ensure filters are always lists
        for key in ['years', 'geography', 'metrics']:
            if key in filters and not isinstance(filters[key], list):
                filters[key] = [filters[key]]

        mapped_metrics = []
        for metric in filters.get('metrics', []):
            attrs = map_metric_to_attributes(metric)
            mapped_metrics.extend(attrs)
        mapped_metrics = list(set(mapped_metrics))  # Remove duplicates
        if not mapped_metrics:
            return jsonify({"error": "No matching metrics found in metadata."}), 404

        # 2. Filter the DataFrame
        try:
            filtered = df[
                (df['Year'].isin(filters['years'])) &
                (df['Geography'].isin(filters['geography'])) &
                (df['Category'].isin(mapped_metrics))
            ]
        except Exception as e:
            return jsonify({"error": f"Error filtering data: {str(e)}"}), 500

        if filtered.empty:
            if filtered.empty:
                # Check which filter caused the empty result
                # 1. Check years
                years_in_data = set(df['Year'])
                years_requested = set(filters['years'])
                if not years_in_data.intersection(years_requested):
                    return jsonify({"error": f"No data found for the selected year(s): {filters['years']}."}), 404

                # 2. Check geography
                geo_in_data = set(df['Geography'])
                geo_requested = set(filters['geography'])
                if not geo_in_data.intersection(geo_requested):
                    return jsonify({"error": f"No data found for the selected geography/geographies: {filters['geography']}."}), 404

                # 3. Check metrics (elements)
                cat_in_data = set(df['Category'])
                cat_requested = set(mapped_metrics)
                if not cat_in_data.intersection(cat_requested):
                    return jsonify({"error": f"No data found for the selected metric(s): {filters['metrics']}."}), 404

                # If all exist individually, but not together
                return jsonify({"error": "No data found for your query with the selected combination of filters."}), 404

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

        try:
            wide_df = filtered.pivot_table(
                index=['Year', 'Geography'],
                columns='Category',
                values=filtered.columns[-1],  # Assuming the value column is the last one
                aggfunc='first'
            ).reset_index()
            # Flatten MultiIndex columns if needed
            wide_df.columns = [str(col) for col in wide_df.columns]
            # Rename metric columns to Display_Text
            new_columns = []
            for col in wide_df.columns:
                if col in attribute_to_displaytext:
                    new_columns.append(attribute_to_displaytext[col])
                else:
                    new_columns.append(col)
            wide_df.columns = new_columns
            table_html = wide_df.head(10).to_html(index=False)
        except Exception as e:
            # Fallback to long format if pivot fails
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
