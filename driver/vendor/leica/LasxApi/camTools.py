# camTools.py
# Autor: Frank Sieckmann
# Created: 19. Januar 2024
# Last Update: 15. Februar 2024
# Lizenz: Leica Micosystems CMS GmbH

__version__ = '1.7.0'
__created__ = '27.02.2024'


from scyjava import jimport, to_python
from napari import view_image
from numpy import moveaxis
from PIL import Image
import numpy as np
import itertools
import skimage
import xarray
import imagej
import napari
import sys
import os


def load_cells3d_sample_data():
    """
    Loads a sample 3D cell image dataset using the skimage library.

    This function is a utility for quickly accessing a standard 3D cell image dataset.
    It uses the skimage.data module to load a sample dataset that contains 3D images of cells.
    This can be useful for testing, demonstrations, or as a starting point for image processing workflows.

    Returns:
    - np.ndarray: A NumPy array containing the 3D cell image data. The dimensions of the array represent
      the spatial dimensions and channels of the sample 3D cell images.
    """
    npy_cells = skimage.data.cells3d()
    return npy_cells


def initialize_runtime():
    """
    Imports and initializes the Java Runtime environment.

    This function is designed to import and initialize the Java Runtime using Jython or a similar
    Java integration environment for Python. It provides access to the Java Runtime environment,
    which can be useful for executing Java code, managing Java objects, or interacting with the
    Java ecosystem within a Python application.

    Returns:
    - java.lang.Runtime: An instance of the Java Runtime class, which allows interaction with
      the Java Runtime environment.
    """
    Runtime = jimport('java.lang.Runtime')
    return Runtime


def initialize_imagej():
    """
    Initializes and returns an instance of ImageJ.

    This function is designed to initialize ImageJ, a popular image processing program widely used
    in scientific imaging. It specifically initializes ImageJ in 'interactive' mode, which is
    suitable for scenarios where interaction with the ImageJ GUI is required. This can be useful
    in contexts where Python is used to automate or extend the functionality of ImageJ.

    Returns:
    - imagej.ImageJ: An instance of the ImageJ application, ready for interactive use.
    """
    ij = imagej.init(mode='interactive')
    return ij


def initialize_imagej_fiji(fiji_path):
    """
    Initializes the ImageJ environment with a specific Fiji installation.

    Parameters:
    fiji_path (str): The file path to the local Fiji installation. This path must be accurate
                     and point to the location where Fiji is installed on your system.

    This method initializes ImageJ in 'interactive' mode, which is suitable for tasks that
    require the graphical user interface, such as displaying images. If the specified path
    or the installation is incorrect, the initialization will fail.

    Returns:
        ij: The initialized ImageJ instance.
    """

    # Initialize ImageJ with the specified Fiji installation in interactive mode.
    # The 'interactive' mode allows using ImageJ's graphical features.
    ij = imagej.init(fiji_path, mode='interactive')

    # Return the initialized ImageJ instance for further use.
    return ij


def create_java_4d_xarray_cells(npy_cells, ij):
    """
    Converts a NumPy array of cell images into a Java-compatible xarray DataArray, and then into a Java object.

    This function takes a 4D NumPy array containing cell image data and converts it into an xarray DataArray.
    This xarray DataArray is then converted into a Java object using ImageJ's Python-Java integration,
    making it accessible and usable within the Java environment, particularly in ImageJ.

    Parameters:
    - npy_cells (np.ndarray): A 4-dimensional NumPy array containing cell image data. The dimensions are expected
      to represent planes, channels, rows, and columns.
    - ij (imagej.ImageJ): An instance of the ImageJ application, used for the Python-Java conversion.

    Returns:
    - java.lang.Object: A Java object representing the xarray DataArray of cell images, compatible with Java
      and ImageJ operations.

    The function first creates an xarray DataArray with appropriate dimension labels from the NumPy array.
    It then uses ImageJ's 'py.to_java' method to convert this xarray DataArray into a Java object.
    This Java object can be used within ImageJ for further image processing or analysis.
    """
    xarray_cells = xarray_cells = xarray.DataArray(npy_cells, name='xarray_cells', dims=('pln', 'ch', 'row', 'col'))
    java_xarray_cells = ij.py.to_java(xarray_cells)
    return java_xarray_cells


def get_image_details(image):
    """
    Outputs the metadata of an image data array.

    This function is designed to extract and print metadata information from an image object.
    It can handle different types of image objects, such as xarray DataArray, ImageJ Dataset,
    or ImageJ ImagePlus. The function prints the name, type, data type, shape, and dimensions
    of the image, providing a quick overview of its properties.

    Parameters:
    - image: The image object from which to extract metadata. This can be an xarray DataArray,
      an ImageJ Dataset, or an ImageJ ImagePlus.

    The function first attempts to find the name of the image from various attributes, depending
    on the type of the image object. It then prints the type, data type (dtype), shape, and dimensions
    (dims) of the image. If certain attributes are not present in the image object, it prints 'N/A'.
    """
    name = image.name if hasattr(image, 'name') else None # xarray
    if name is None and hasattr(image, 'getName'): name = image.getName() # Dataset
    if name is None and hasattr(image, 'getTitle'): name = image.getTitle() # ImagePlus
    print(f" name of image: {name or 'N/A'}")
    print(f" type of image: {type(image)}")
    print(f"dtype of image: {image.dtype if hasattr(image, 'dtype') else 'N/A'}")
    print("\033[32mshape of image:", image.shape, "\033[0m")
    print(f"\033[34m dims of image: {image.dims if hasattr(image, 'dims') else 'N/A'}\033[0m")


def extract_filename_path(path):
    """
    Extracts and returns the base name (filename without extension) from a given file path.

    Parameters:
    - path (str): A string representing the full path of the file, including directories, filename, and extension.

    Returns:
    - str: The base name of the file, extracted from the provided full file path.
    """
    filename = path.split("\\")[-1].split(".")[0]
    return filename


def generate_permutations_for_pattern(base_filename, pattern="LTZC"):
    """
    Generates all permutations of a given filename pattern. This function is useful for creating a list of filenames
    that vary in specified parts defined by the pattern.

    Parameters:
    - base_filename (str): The base filename from which to generate permutations. It should contain tokens separated by "--".
    - pattern (str, optional): A string representing the tokens to permute in the base filename.
      Defaults to "LTZC", meaning it looks for tokens starting with 'L', 'T', 'Z', and 'C'.

    Returns:
    - list of str: A list of generated filenames with all permutations of the specified tokens in the pattern.

    The function splits the base filename into tokens, identifies the tokens that match the pattern, and generates
    all possible combinations of these tokens' values. Each combination is then merged back into the filename format.
    """
    tokens = base_filename.split("--")
    token_values = {t[0]: (int(t[1:]), len(t) - 1) for t in tokens if t[0] in pattern}
    ranges = {t: range(token_values[t][0] + 1) for t in pattern}
    all_combinations = itertools.product(*(ranges[t] for t in pattern))
    generated_filenames = []
    for combination in all_combinations:
        filename_parts = tokens.copy()
        for t, value in zip(pattern, combination):
            token_index = next(i for i, part in enumerate(filename_parts) if part.startswith(t))
            formatted_value = f"{value:0{token_values[t][1]}d}"
            filename_parts[token_index] = f"{t}{formatted_value}"
        generated_filenames.append("--".join(filename_parts))
    return generated_filenames


def generate_permutations_with_full_path_and_extension(path, pattern="LTZC"):
    """
    Generates a list of file paths with permutations based on a specified pattern, maintaining the original directory
    path and file extension. This function is useful for creating variations of a base filename within the same directory.

    Parameters:
    - path (str): The full path of the base file including the directory, filename, and extension.
    - pattern (str, optional): A string representing the tokens in the filename to be permuted.
      Defaults to "LTZC", indicating that tokens starting with 'L', 'T', 'Z', and 'C' will be permuted.

    Returns:
    - list of str: A list of file paths with permuted filenames based on the specified pattern, preserving the original
      directory path and file extension.

    The function splits the full path to extract the directory path and filename. It then generates permutations of
    the filename based on the specified pattern and reassembles these filenames with the original directory path and
    file extension to form full file paths.
    """
    path_parts = path.split("\\")
    directory_path = "\\".join(path_parts[:-1])
    original_filename = path_parts[-1]
    filename_without_extension, extension = original_filename.split(".")[0], "." + ".".join(original_filename.split(".")[1:])
    permutations = generate_permutations_for_pattern(filename_without_extension, pattern)
    generated_full_paths_with_extension = [directory_path + "\\" + filename + extension for filename in permutations]
    return generated_full_paths_with_extension


def load_images_from_path_list(path_list):
    """
    Loads images from a list of file paths into a NumPy array.

    Parameters:
    - path_list (list of str): A list of file paths from which images will be loaded.

    Returns:
    - np.ndarray: A NumPy array containing all the loaded images. The array dimensions are [num_images, height, width],
      where 'num_images' is the number of images in the path_list, and 'height' and 'width' are the dimensions of each image.

    Each image in the path_list is loaded and stored in a 2D array (assuming grayscale images). The function assumes
    all images have the same dimensions (512x512 pixels in this case). If a path does not point to a valid file,
    it is skipped without loading an image.
    """
    height, width = 512, 512  # Example values, adjust according to the actual image size
    num_images = len(path_list)
    images_array = np.zeros((num_images, height, width))
    for i, image_path in enumerate(path_list):
        if os.path.exists(image_path):
            image = Image.open(image_path)
            images_array[i, :, :] = np.array(image)
    return images_array


def print_array_dims(array):
    """
    Prints the dimensions of a given image array in a readable format.

    Parameters:
    - array (np.ndarray): A NumPy array representing an image or a set of images.
      The array is expected to have dimensions corresponding to 'C', 'Z', 'X', 'Y'.

    This function takes an image array and prints its dimensions in a human-readable format.
    It maps the array's shape to dimension labels 'C' (Channels), 'Z' (Depth), 'X' (Width), and 'Y' (Height).
    This is useful for quickly understanding the structure of the image data, especially in multidimensional image processing.
    """
    dims = ['C', 'Z', 'X', 'Y']  # List of dimensions
    shape = array.shape
    dims_description = ", ".join(f"{dim} = {size}" for dim, size in zip(dims, shape))
    print(f"Image Array Dimension: {dims_description}")


def print_list_elements(list):
    """
    Druckt jedes Element einer Liste in einer neuen Zeile.

    Diese Methode geht durch jedes Element in der Ã¼bergebenen Liste und druckt es aus.
    Dadurch erscheint jedes Element auf einer separaten Zeile in der Konsole.
    Dies ist nÃ¼tzlich, wenn Sie eine klare und lesbare Darstellung der Listenelemente wÃ¼nschen.

    Parameters:
    list (list): Die Liste der Elemente, die ausgedruckt werden sollen.
    """

    # Durchgehen jedes Elements in der Liste und Ausdrucken in einer neuen Zeile
    for element in list:
        print(element)


def load_images_into_4d_array(path_list, num_channels, num_planes):
    """
    Loads images from a list of file paths into a 4D array with dimensions [C, Z, X, Y].

    This function is designed to take a list of image file paths and load these images into a
    4D NumPy array. The dimensions of the array are intended to represent Channels (C),
    Depth/Planes (Z), Height (X), and Width (Y). It's suitable for processing multichannel
    and/or z-stacked images typically used in scientific imaging.

    Parameters:
    - path_list (list of str): A list of file paths from which images will be loaded.
    - num_channels (int): The number of channels (C) in the image data.
    - num_planes (int): The number of z-planes (Z) in the image data.

    Returns:
    - np.ndarray: A 4D NumPy array containing the loaded images, arranged in the order of channels,
      z-planes, height, and width.

    The function iterates over the provided file paths, extracting channel and z-plane indices from
    the filenames. Each image is loaded into the array at the corresponding [C, Z] location.
    The function assumes all images are of the same size (height and width).
    """
    height, width = 512, 512  # Example values, adjust according to actual image size
    images_array = np.zeros((num_channels, num_planes, height, width))

    for image_path in path_list:
        # Extract channel and z-plane indices from the filename
        filename = os.path.basename(image_path).split(".")[0]  # Remove file extension
        parts = filename.split("--")
        c_index = int(next(part.replace("C", "") for part in parts if part.startswith("C")))
        z_index = int(next(part.replace("Z", "") for part in parts if part.startswith("Z")))

        # Load the image if it exists
        if os.path.exists(image_path):
            image = Image.open(image_path)
            images_array[c_index, z_index, :, :] = np.array(image)

    return images_array


def convert_numpy_to_imagej(numpy_array, ij_instance):
    """
    Konvertiert ein NumPy-Array in ein ImageJ-kompatibles Java-Array.

    Diese Methode nimmt ein NumPy-Array und eine ImageJ-Instanz als Eingabe und konvertiert
    das NumPy-Array in ein Format, das von ImageJ verarbeitet werden kann. Dies ist nÃ¼tzlich,
    um Bildverarbeitungsaufgaben oder Analysen, die in NumPy durchgefÃ¼hrt wurden, in die
    ImageJ-Umgebung zu integrieren.

    Parameters:
    numpy_array (np.array): Das NumPy-Array, das konvertiert werden soll.
    ij_instance (imagej.ImageJ): Die Instanz von ImageJ, die fÃ¼r die Konvertierung verwendet wird.

    Returns:
    java_image: Ein Java-Array, das von ImageJ verarbeitet werden kann.
    """

    # Konvertieren des NumPy-Arrays in ein ImageJ-kompatibles Dataset
    java_image = ij_instance.py.to_dataset(numpy_array)

    return java_image


def process_results_table(ResultsTable):
    """
    Processes an ImageJ ResultsTable and converts it to a list of dictionaries.

    Each dictionary in the list represents a row in the ResultsTable, with keys
    being the column headings and values being the data points for that row.

    Args:
    ResultsTable (ij.measure.ResultsTable): The ImageJ ResultsTable to process.

    Returns:
    list of dict: A list of dictionaries representing the rows of the ResultsTable.
                  Returns None if the table contains no data.
    """
    results_table = ResultsTable.getResultsTable()

    # Print the number of columns and rows
    column_count = results_table.getHeadings().length
    row_count = results_table.size()

    print("Number of columns:", column_count)
    print("Number of rows:", row_count)

    # Only process data if the table is not empty
    if row_count > 0:
        results = []
        for i in range(row_count):
            row = {}
            for j in range(column_count):
                column_heading = results_table.getColumnHeading(j)
                column_values = to_python(results_table.getColumn(j))

                # ÃœberprÃ¼fen, ob der Wert None ist und ggf. durch 0 ersetzen
                if column_values is not None and i < len(column_values):
                    value = column_values[i]
                    if value is None:
                        value = 0
                    row[column_heading] = value
                else:
                    row[column_heading] = 0  # Standardwert, wenn keine Daten vorhanden sind
            results.append(row)
        return results
    else:
        print("The table contains no data.")
        return None


def GetSUVXY_From_FileName(path):
    """
    Extracts five numerical values (S, U, V, X, Y) from a given file path based on a specific pattern.

    This method uses a regular expression pattern to search for and extract five specific integer values from the file path.
    These values are identified by the letters S, U, V, X, and Y, each followed by a numerical value. The format in the file path
    should match the pattern, e.g., "--S<num>--U<num>--V<num>--...--X<num>--Y<num>--...".

    Parameters:
    path (str): The file path string from which the values are to be extracted.

    Returns:
    tuple: A tuple containing the extracted integer values (S, U, V, X, Y) in the same order.

    Raises:
    ValueError: If the pattern is not found in the provided path, indicating an incorrect format.
    """

    # Regular expression pattern for finding the desired values
    pattern = r".*--S(\d+)--U(\d+)--V(\d+)--.*--X(\d+)--Y(\d+)--.*"

    # Extracting values from the file name
    match = re.search(pattern, path)
    if match:
        S, U, V, X, Y = map(int, match.groups())
        return S, U, V, X, Y
    else:
        raise ValueError("The expected SUVXY pattern was not found in the path.")


def convert_microns_to_meter(micrometer):
    meter = micrometer / 1_000_000.0
    return meter
