# https://github.com/CSAILVision/places365
# https://github.com/surya501/reverse-image-search


from annoy import AnnoyIndex
from geopy.geocoders import Nominatim
import matplotlib.pyplot as plt
from matplotlib.pyplot import imshow
import os
import pickle
from PIL import Image
import pandas as pd
import numpy as np
import plotly.express as px
import seaborn as sns
sns.set_style("darkgrid")
import torch
import torch.nn as nn
import torchvision.models as models
from torchvision import transforms as trn
import config as cfg


# define image transformer
transform = trn.Compose([trn.Resize(cfg.RESIZE),
                               trn.CenterCrop(cfg.CROP),
                               trn.ToTensor(),
                               trn.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
                              ])

def load_pretrained_model(arch='resnet18'):
    '''
    Loads the pretrained PyTorch CNN models pretrained on places365 dataset.
    Model options are 'alexnet','densenet161','resnet18', and 'resnet50'.
    By default the 'resnet18' architecture is chosen for its lowest memory.
    Class labels follow 'categories_places365.txt'.
    :return: model for generating feature embeddings and full model for class label prediction
    '''

    # make sure os.getcwd() returns the project home directory.
    model_file = 'places365/%s_places365.pth.tar' %arch

    # load pre-trained weights
    model = models.__dict__[arch](num_classes=cfg.NUMCLASS)
    model_full = models.__dict__[arch](num_classes=cfg.NUMCLASS)
    checkpoint = torch.load(model_file, map_location=lambda storage, loc: storage)
    state_dict = {str.replace(k, 'module.', ''): v for k, v in checkpoint['state_dict'].items()}
    model.load_state_dict(state_dict)
    model_full.load_state_dict(state_dict)
    model.fc_backup = model.fc
    model.fc = nn.Sequential()
    model_full.eval()

    return model, model_full


def load_pkl_paths(folder):
    '''
    :param folder: the path of the 'data' folder
    :return: a list of paths to pickle files that store the geo data
    '''
    # pass in the 'data' folder as 'folder'
    class_names = [fold for fold in os.listdir(folder)]  # this should get folder names at the 'abbey' level
    paths_list = []
    for cl in class_names:
        img_files = [f for f in os.listdir(os.path.join(folder, cl)) if '.pkl' in f]

        for img in img_files:
            full_path = os.path.join(folder, cl, img)
            paths_list.append(full_path)

    df = pd.DataFrame(paths_list, columns=['path'])
    return df


def get_vector_index(model, image_loader):
    """
    Evaluate model to get vector embeddings (features) and build tree for annoy indexing
    Arguments:
        model -- pre-trainned imagenet model to use.
        image_loader -- pytorch image_loader
    Returns:
        [annoy index] -- can be used for querying
    """
    t = AnnoyIndex(cfg.RESNET18_FEAT, metric=cfg.ANNOY_METRIC)  # 512 for resnet18
    with torch.no_grad():
        model.eval()
        for batch_idx, (data, target) in enumerate(image_loader):
            outputs = model(data)
            for i in range(0, len(data)):
                t.add_item(target[i], outputs[i])
    t.build(cfg.ANNOY_TREE)
    return t


def eval_test_image(test_img, model, annoy_index, top_n=5):
    '''
    Search for the closest image as the test iamge.
    :param test_img: path of test image
    :param model:
    :param annoy_index:
    :return:
    '''
    with torch.no_grad():
        model.eval()
        data = Image.open(test_img,'r').convert('RGB')
        data = transform(data).unsqueeze(0)
#         img_loader = DataLoader(data)
#         for idx, img in enumerate(img_loader):
        feature = model(data)
    searches = annoy_index.get_nns_by_vector(feature[0], top_n, include_distances=True)
    return searches[0], searches[1]


def plot_input_and_similar(test_img, searches, pd, titles=None):
    '''
    Use this function instead of plot_similar.
    test_img: text path to test image
    searches: tuple of lists. index[0] is a list of similar indices. index[1] is a list of cosine distances (flat_list)
    pd: dataframe of paths
    '''
    idx = searches[0]
    titles = searches[1]

    f = plt.figure(figsize=(10, 15))
    plt.subplots_adjust(left=0.1, bottom=0, right=0.2, top=1.02, wspace=0.02, hspace=0.02)
    plt.axis('Off')
    rows = len(idx)
    cols = 2
    for i, img_idx in enumerate(idx):
        sp = f.add_subplot(rows, cols, 2 * (i + 1))  # want the output pictures on the right side
        sp.axis('Off')
        sp.get_xaxis().set_visible(False)
        sp.get_yaxis().set_visible(False)
        if titles is not None:
            sp.set_title('Cosine diff = %.3f' % titles[i], fontsize=16)
        data = Image.open(pd.iloc[img_idx].path, 'r')
        data = data.convert('RGB')
        data = data.resize((400, 300), Image.ANTIALIAS)
        plt.imshow(data)
        plt.tight_layout()

    # plot test image
    sp = f.add_subplot(rows, cols, rows)  # want the test image in the middle of the column
    sp.axis('Off')
    sp.get_xaxis().set_visible(False)
    sp.get_yaxis().set_visible(False)
    sp.set_title('User Input', fontsize=16)
    data = Image.open(test_img, 'r')
    data = data.convert('RGB')
    data = data.resize((400, 300), Image.ANTIALIAS)
    plt.imshow(data)
    plt.tight_layout()
    plt.autoscale(tight=True)


def create_df_for_map_plot(searches, pd_files):
    '''
    :param searches: search results from evalTestImage()
    :param pd_files: pandas DataFrame from ImageDataset.get_file_df()
    :return: DataFrame of the searches' location and address
    '''
    idx = searches[0]  # list of annoy index results
    labels = pd_files.iloc[idx].label
    class_labels = list(labels.drop_duplicates()) # avoid looking up the same label multiple times
    name = list(pd_files.iloc[idx]['name'].str.rstrip('.jpg'))  # list of photo id's

    for_plotly = pd.DataFrame(columns=['latitude', 'longitude'])
    for label in class_labels:
        with open('data/%s/%s.pkl' % (label, label), 'rb') as f:
            locations = pickle.load(f)
            for_plotly = pd.concat(
                [locations.loc[locations['id'].isin(name)][['latitude', 'longitude']], for_plotly])
            f.close()

    for_plotly['paths'] = list(pd_files.iloc[idx]['sub_paths'])
    for_plotly['paths'] = for_plotly['paths'].str.replace('\\','/')
    for_plotly['labels'] = list(labels)
    for_plotly['cos_diff'] = np.around(searches[1], 3)
    for_plotly = for_plotly.reset_index(drop=True)
    gl = Nominatim(user_agent='default')
    for_plotly['latlon'] = list(zip(for_plotly['latitude'], for_plotly['longitude'])) # for GeoPy reverse method
    for_plotly['address'] = for_plotly['latlon'].apply(gl.reverse)

    return for_plotly


def plot_map(searches, pd_files):
    '''
    Plots search results on a map
    :param searches: search results from evalTestImage()
    :param pd_files: pandas DataFrame from ImageDataset.get_file_df()
    '''
    df = create_df_for_map_plot(searches, pd_files)
    fig = px.scatter_geo(df, lat='latitude', lon='longitude', text='display')
    fig.show()

