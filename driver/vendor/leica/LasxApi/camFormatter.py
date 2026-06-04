# camTools.py
# Autor: Frank Sieckmann
# Created: 19. Februar 2024
# Last Update: 19. Februar 2024
# Lizenz: Leica Micosystems CMS GmbH

__version__ = '1.0.0'
__created__ = '19.02.2024'


from IPython.display import display, HTML, Javascript
import json
import time
import sys

def get_help_icon_data_uri():
    return "data:image/png;base64,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"


def format_universal_help_as_html(help_data, heading, indent_name=1, indent_description=20, python_sample_box_width=1000):
    # Specific color information and styles defined at the beginning
    heading_color = "#800080"  # Purple for the heading
    entry_name_color = "#2E5894"  # Blue for the entry names and type/return details
    description_text_color = "#000000"  # Black for the description text
    code_background_color = "#333333"  # Dark gray background for code
    code_text_color = "#FFFFFF"  # White for the code text
    code_label_color = "#ADD8E6"  # Light blue for the "Python Sample Code:" label
    code_border_color = "#6495ed"  # White border for code box
    version_text_color = "#333333"  # Dark gray for the version text
    background_color = "#F0F0F0"  # Light gray

    box_style = f"border: 1px solid {entry_name_color}; background-color: {background_color}; padding: 10px; border-radius: 5px; margin-bottom: 10px; position: relative;"
    grid_style = "display: grid; grid-template-columns: max-content auto; column-gap: 10px; align-items: start; grid-row-gap: 4px;"
    version_info_style = "position: absolute; bottom: 10px; right: 10px; color: {version_text_color};"
    icon_style = "position: absolute; top: 10px; right: 10px; width: 60px; height: 60px;"
    help_icon_data_uri = get_help_icon_data_uri()

    # Start constructing the HTML output
    html_output = f"<div style='{box_style}'>"
    html_output += f"<img src='{help_icon_data_uri}' style='{icon_style}' alt='Help Icon'/>"
    html_output += f"<div style='{grid_style}'>"
    html_output += f"<span style='color: {heading_color}; font-weight: bold; text-decoration: underline; grid-column: 1 / -1;'>Help for the CAM Command -- {heading}</span>"

    # Iterate through each item in the help_data dictionary
    for key, value in help_data.items():
        name = value.get("Name", "N/A")
        type_ = value.get("Type", "N/A")
        return_ = value.get("Return", "N/A")
        description = value.get("Description", "N/A").replace("\n", "<br>")
        sample_code_python = value.get("SampleCodePython", "--")

        # Construct the section for this item
        html_output += f"<div style='grid-column: 1 / -1;'><span style='font-weight: bold; color: {entry_name_color}; margin-left: {indent_name}em;'>{name}:</span> <span style='color: {entry_name_color};'>(Type: {type_}, Return: {return_}) </span></div>"
        description_div = f"<div style='grid-column: 2 / -1; color: {description_text_color}; margin-left: {indent_description}em;'>{description}<br>"
        if sample_code_python != "--":
            # Formatting the Python sample code in a box with a specific width
            description_div += f"<div style='display: inline-block; background-color: {code_background_color}; color: {code_text_color}; border: 1px solid {code_border_color}; padding: 5px; border-radius: 4px; font-family: monospace; margin-top: 5px; width: {python_sample_box_width}px; overflow: auto;'><span style='color: {code_label_color};'>Python Sample Code:</span> {sample_code_python}</div>"
        description_div += "</div>"
        html_output += description_div

        # If there are values associated with this item, list them
        if 'Values' in value and value['Values']:
            html_output += f"<div style='grid-column: 2 / -1; margin-left: {indent_description}em;'><ul>"
            for val in value['Values']:
                val_description = val['Description'].replace("\n", "<br>")
                html_output += f"<li style='color: {description_text_color};'>{val['Value']}: {val_description}</li>"
            html_output += "</ul></div>"

    # Close the grid container, add version info, and close the main container
    html_output += "</div>"
    html_output += f"<div style='{version_info_style}'>Leica Microsystems -- FS CAM Version 6</div>"
    html_output += "</div>"  # End of the main container

    return html_output


def display_camapi_help(help_json, heading):
    universal_help_data = json.loads(help_json)
    formatted_html = format_universal_help_as_html(universal_help_data, heading)
    display(HTML(formatted_html))


def format_experiment_info_as_html(navigator_expert_client_name, navigator_expert_version, lasx_version, scan_status, scanning_template, jobs):
    # Specific color information
    text_color = "#2E5894"  # blue
    background_color = "#D0E0F0"  # light blue

    # Box style with updated colours
    box_style = f"border: 1px solid {text_color}; background-color: {background_color}; padding: 10px; border-radius: 5px; margin-bottom: 10px;"

    # CSS Grid for alignment
    grid_style = "display: grid; grid-template-columns: max-content auto; column-gap: 10px; align-items: center;"

    # Create the HTML string with the selected styles
    html_output = f"""<div style="{box_style}">
    <div style="{grid_style}">
        <span style="color: {text_color}; font-weight: bold; text-decoration: underline; grid-column: 1 / -1;">Experiment Information</span>
        <span style="font-weight: bold;">Version Navigator Client:</span> <span>{navigator_expert_client_name}</span>
        <span style="font-weight: bold;">Version Navigator Expert:</span> <span>{navigator_expert_version}</span>
        <span style="font-weight: bold;">Version LASX:</span> <span>{lasx_version}</span>
        <span style="font-weight: bold;">Scan Status:</span> <span>{scan_status}</span>
        <span style="font-weight: bold;">Scanning Template:</span> <span>{scanning_template}</span>
        <span style="font-weight: bold;">Available Jobs:</span> <span>{jobs}</span>
    </div>
    </div>"""
    return html_output


def format_as_html(error_type, message, solution):
    # Normalisation and ensuring that the error_type is a usable string
    error_type = str(error_type).strip()
    # Conversion to a formatted string, if necessary
    error_type_formatted = error_type.title()

    # Update the colors and background colors to make the background lighter
    colors = {
        "Critical": ("#8B0000", "#FAB4B4"),  # Darker red for Critical and even lighter for the background
        "Information": ("#008000", "#C1ECC1"),  # Green and lighter for the background
        "Warning": ("#FFA500", "#FFECB5"),  # Orange and lighter for the background
        "Error": ("#FF0000", "#FFD1D1"),  # Red and lighter for the background
    }
    color, background_color = colors.get(error_type_formatted, ("black", "#f0f0f0"))

    # Define the style for the box with the colour and the even lighter background
    box_style = f"border: 1px solid {color}; background-color: {background_color}; padding: 10px; border-radius: 5px; margin-bottom: 10px;"

    # Create the HTML string with the selected styles for the entire text and the box
    html_output = f"""<div style="{box_style}">
    <span style="color: {color}; font-weight: bold; text-decoration: underline;">{error_type_formatted}</span><br>
    <span style="font-weight: bold;">Message:</span> {message}<br>
    <span style="font-weight: bold;">Solution:</span> {solution}
    </div>"""
    return html_output
