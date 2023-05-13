#!/usr/bin/env python
# coding: utf-8

# # SocraticFlanT5 - Caption Generation (baseline) | DL2 Project, May 2023
# ---
# 
# This notebook downloads the images from the validation split of the [MS COCO Dataset (2017 version)](https://cocodataset.org/#download) and the corresponding ground-truth captions and generates captions based on the Socratic model pipeline outlined below. The caption will be generated by the baseline approach:
# * Baseline: a Socratic model based on the work by [Zeng et al. (2022)](https://socraticmodels.github.io/) where GPT-3 is replaced by [FLAN-T5-xl](https://huggingface.co/docs/transformers/model_doc/flan-t5). 
# 
# In other words, the goal of this jupyter notebook is to reproduce the Socratic Models paper with the Flan-T5 model. This provides a baseline for us to build upon.

# ## Set-up
# If you haven't done so already, please activate the corresponding environment by running in the terminal: `conda env create -f environment.yml`. Then type `conda activate socratic`.

# ### Loading the required packages

# In[9]:


# Package loading
import matplotlib.pyplot as plt
import pandas as pd
from transformers import set_seed
import os
import numpy as np
import re
import pickle
import time
import random
import pandas as pd

# Local imports
from image_captioning import ClipManager, ImageManager, VocabManager, FlanT5Manager
from image_captioning import LmPromptGenerator as pg
from utils import get_device


# ### Set seeds for reproducible results

# In[11]:


# Set HuggingFace seed
set_seed(42)

# Set seed for 100 random images of the MS COCO validation split
random.seed(42)


# ## Step 1: Downloading the MS COCO images and annotations

# In[3]:


imgs_folder = 'imgs/val2017/'
annotation_file = 'annotations/annotations/captions_val2017.json'

coco_manager = COCOManager()
coco_manager.download_data()


# ## Step 2: Generating the captions via the Socratic pipeline
# 

# ### Set the device and instantiate managers

# In[4]:


# Set the device to use
device = get_device()

# Instantiate the clip manager
clip_manager = ClipManager(device)

# Instantiate the image manager
image_manager = ImageManager()

# Instantiate the vocab manager
vocab_manager = VocabManager()


# ### Compute place and object features

# In[5]:


# Calculate the place features
if not os.path.exists('cache/place_feats.npy'):
    # Calculate the place features
    place_feats = clip_manager.get_text_feats([f'Photo of a {p}.' for p in vocab_manager.place_list])
    np.save('cache/place_feats.npy', place_feats)
else:
    place_feats = np.load('cache/place_feats.npy')

# Calculate the object features
if not os.path.exists('cache/object_feats.npy'):
    # Calculate the object features
    object_feats = clip_manager.get_text_feats([f'Photo of a {o}.' for o in vocab_manager.object_list])
    np.save('cache/object_feats.npy', object_feats)
else:
    object_feats = np.load('cache/object_feats.npy')


# ### Load images and compute image embedding

# In[ ]:


approach = 'baseline'
caption_file_path = f'cache/res_{approach}.pickle'
caption_embed_file_path = f'cache/embed_capt_res_{approach}.pickle'

img_dic = {}
img_feat_dic = {}
if not os.path.exists(caption_file_path):
    # N = len(os.listdir(imgs_folder))
    N = 100
    random_numbers = random.sample(range(len(os.listdir(imgs_folder))), N)

    # for ix, file_name in enumerate(os.listdir(imgs_folder)[:N]):
    for ix, file_name in enumerate(os.listdir(imgs_folder)):
         # Consider only image files that are part of the random sample
        if file_name.endswith(".jpg") and ix in random_numbers:  
            # Getting image id
            file_name_strip = file_name.strip('.jpg')
            match = re.search('^0+', file_name_strip)
            sequence = match.group(0)
            image_id = int(file_name_strip[len(sequence):])

            img_path = os.path.join(imgs_folder, file_name)
            img = image_manager.load_image(img_path)
            img_feats = clip_manager.get_img_feats(img)
            img_feats = img_feats.flatten()
            
            img_dic[image_id] = img
            img_feat_dic[image_id] = img_feats


# ### Zero-shot VLM (CLIP)
# We zero-shot prompt CLIP to produce various inferences of an iage, such as image type or the number of people in an image:

# #### Classify image type

# In[ ]:


img_types = ['photo', 'cartoon', 'sketch', 'painting']
img_types_feats = clip_manager.get_text_feats([f'This is a {t}.' for t in img_types])

# Create a dictionary to store the image types
img_type_dic = {}
for img_name, img_feat in img_feat_dic.items():
    sorted_img_types, img_type_scores = clip_manager.get_nn_text(img_types, img_types_feats, img_feat)
    img_type_dic[img_name] = sorted_img_types[0]


# #### Classify number of people

# In[ ]:


ppl_texts_bool = ['no people', 'people']
ppl_feats_bool = clip_manager.get_text_feats([f'There are {p} in this photo.' for p in ppl_texts_bool])

ppl_texts_mult = ['is one person', 'are two people', 'are three people', 'are several people', 'are many people']
ppl_feats_mult = clip_manager.get_text_feats([f'There {p} in this photo.' for p in ppl_texts_mult])

# Create a dictionary to store the number of people
num_people_dic = {}

for img_name, img_feat in img_feat_dic.items():
    sorted_ppl_texts, ppl_scores = clip_manager.get_nn_text(ppl_texts_bool, ppl_feats_bool, img_feat)
    ppl_result = sorted_ppl_texts[0]
    if ppl_result == 'people':
        sorted_ppl_texts, ppl_scores = clip_manager.get_nn_text(ppl_texts_mult, ppl_feats_mult, img_feat)
        ppl_result = sorted_ppl_texts[0]
    else:
        ppl_result = f'are {ppl_result}'

    num_people_dic[img_name] = ppl_result


# #### Classify image place

# In[ ]:


place_topk = 3

# Create a dictionary to store the number of people
location_dic = {}
for img_name, img_feat in img_feat_dic.items():
    sorted_places, places_scores = clip_manager.get_nn_text(vocab_manager.place_list, place_feats, img_feat)
    location_dic[img_name] = sorted_places[0]


# #### Classify image object

# In[ ]:


obj_topk = 10

# Create a dictionary to store the similarity of each object with the images
obj_list_dic = {}
for img_name, img_feat in img_feat_dic.items():
    sorted_obj_texts, obj_scores = clip_manager.get_nn_text(vocab_manager.object_list, object_feats, img_feat)
    object_list = ''
    for i in range(obj_topk):
        object_list += f'{sorted_obj_texts[i]}, '
    object_list = object_list[:-2]
    obj_list_dic[img_name] = object_list


# #### Generate captions

# In[ ]:


num_captions = 50

# Set LM params
model_params = {'temperature': 0.9, 'max_length': 40, 'do_sample': True}

# Create dictionaries to store the outputs
prompt_dic = {}
sorted_caption_map = {}
caption_score_map = {}

for img_name in img_dic:
    # Create the prompt for the language model
    prompt_dic[img_name] = pg.create_baseline_lm_prompt(
        img_type_dic[img_name], num_people_dic[img_name], location_dic[img_name], obj_list_dic[img_name]
    )

    # Generate the caption using the language model
    caption_texts = flan_manager.generate_response(num_captions * [prompt_dic[img_name]], model_params)

    # Zero-shot VLM: rank captions.
    caption_feats = clip_manager.get_text_feats(caption_texts)
    sorted_captions, caption_scores = clip_manager.get_nn_text(caption_texts, caption_feats, img_feat_dic[img_name])
    sorted_caption_map[img_name] = sorted_captions
    caption_score_map[img_name] = dict(zip(sorted_captions, caption_scores))


# ### Save the outputs

# In[ ]:


data_list = []
for img_name in img_dic:
    generated_caption = sorted_caption_map[img_name][0]
    data_list.append({
        'image_name': img_name,
        'image_path': img_paths[img_name],
        'generated_caption': generated_caption,
        'cosine_similarity': caption_score_map[img_name][generated_caption]
    })
pd.DataFrame(data_list).to_csv(f'baseline_outputs.csv', index=False)


# In[ ]:




