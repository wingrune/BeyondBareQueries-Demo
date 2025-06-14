import copy
from collections.abc import Iterable

import torch
import matplotlib
import numpy as np
import open3d as o3d
from loguru import logger
import torch.nn.functional as F


def to_numpy(tensor):
    if isinstance(tensor, np.ndarray):
        return tensor
    return tensor.detach().cpu().numpy()

def to_tensor(numpy_array, device=None):
    if isinstance(numpy_array, torch.Tensor):
        return numpy_array
    if device is None:
        return torch.from_numpy(numpy_array)
    else:
        return torch.from_numpy(numpy_array).to(device)

class DetectionList(list):
    def get_values(self, key, idx:int=None):
        if idx is None:
            return [detection[key] for detection in self]
        else:
            return [detection[key][idx] for detection in self]

    def get_stacked_values_torch(self, key, idx:int=None):
        values = []
        for detection in self:
            v = detection[key]
            if idx is not None:
                v = v[idx]
            if isinstance(v, o3d.geometry.OrientedBoundingBox) or \
                isinstance(v, o3d.geometry.AxisAlignedBoundingBox):
                v = np.asarray(v.get_box_points())
            if isinstance(v, np.ndarray):
                v = torch.from_numpy(v)
            values.append(v)
        return torch.stack(values, dim=0)

    def get_stacked_values_numpy(self, key, idx:int=None):
        values = self.get_stacked_values_torch(key, idx)
        return to_numpy(values)

    def __add__(self, other):
        new_list = copy.deepcopy(self)
        new_list.extend(other)
        return new_list
    
    def __iadd__(self, other):
        self.extend(other)
        return self

    def slice_by_indices(self, index: Iterable[int]):
        '''
        Return a sublist of the current list by indexing
        '''
        new_self = type(self)()
        for i in index:
            new_self.append(self[i])
        return new_self

    def slice_by_mask(self, mask: Iterable[bool]):
        '''
        Return a sublist of the current list by masking
        '''
        new_self = type(self)()
        for i, m in enumerate(mask):
            if m:
                new_self.append(self[i])
        return new_self

    def get_most_common_class(self) -> list[int]:
        classes = []
        for d in self:
            values, counts = np.unique(np.asarray(d['class_id']), return_counts=True)
            most_common_class = values[np.argmax(counts)]
            classes.append(most_common_class)
        return classes

    def color_by_most_common_classes(self, colors_dict: dict[str, list[float]], color_bbox: bool=True):
        '''
        Color the point cloud of each detection by the most common class
        '''
        classes = self.get_most_common_class()
        for d, c in zip(self, classes):
            color = colors_dict[str(c)]
            d['pcd'].paint_uniform_color(color)
            if color_bbox:
                d['bbox'].color = color

    def color_by_instance(self):
        if len(self) == 0:
            # Do nothing
            return

        if "inst_color" in self[0]:
            for d in self:
                d['pcd'].paint_uniform_color(d['inst_color'])
                d['bbox'].color = d['inst_color']
        else:
            cmap = matplotlib.colormaps.get_cmap("turbo")
            instance_colors = cmap(np.linspace(0, 1, len(self)))
            instance_colors = instance_colors[:, :3]
            for i in range(len(self)):
                self[i]['pcd'].paint_uniform_color(instance_colors[i])
                self[i]['bbox'].color = instance_colors[i]


class MapObjectList(DetectionList):
    def compute_similarities(self, new_features):
        '''
        The input feature should be of shape (D, ), a one-row vector
        This is mostly for backward compatibility
        '''
        # if it is a numpy array, make it a tensor 
        new_features = to_tensor(new_features)

        # assuming cosine similarity for features
        features = self.get_stacked_values_torch('descriptor')

        similarities = F.cosine_similarity(new_features.unsqueeze(0), features)
        return similarities

    def to_serializable(self):
        s_obj_list = []
        for obj in self:
            s_obj_dict = copy.deepcopy(obj)

            #s_obj_dict['pcd_np'] = np.asarray(s_obj_dict['pcd'].points)
            #s_obj_dict['bbox_np'] = np.asarray(s_obj_dict['bbox'].get_box_points())
            #s_obj_dict['pcd_color_np'] = np.asarray(s_obj_dict['pcd'].colors)

            try:
                s_obj_dict['descriptor'] = to_numpy(s_obj_dict['descriptor'])
            except:
                logger.warning("can't load descriptor")

            try:
                s_obj_dict['id'] = list(s_obj_dict['id'])
            except:
                logger.warning("can't load id")

            del s_obj_dict['pcd']
            del s_obj_dict['bbox']
            
            s_obj_list.append(s_obj_dict)
            
        return s_obj_list
    
    def load_serializable(self, s_obj_list):
        assert len(self) == 0, 'MapObjectList should be empty when loading'
        for s_obj_dict in s_obj_list:
            new_obj = copy.deepcopy(s_obj_dict)

            new_obj['pcd'] = o3d.geometry.PointCloud()
            new_obj['pcd'].points = o3d.utility.Vector3dVector(new_obj['pcd_np'])
            new_obj['bbox'] = o3d.geometry.OrientedBoundingBox.create_from_points(
                o3d.utility.Vector3dVector(new_obj['bbox_np']))
            new_obj['bbox'].color = new_obj['pcd_color_np'][0]
            new_obj['pcd'].colors = o3d.utility.Vector3dVector(new_obj['pcd_color_np'])

            try:
                new_obj['descriptor'] = to_tensor(new_obj['descriptor'])
            except:
                logger.warning("can't load descriptor")

            try:
                new_obj['id'] = set(new_obj['id'])
            except:
                logger.warning("can't load id")

            del new_obj['pcd_np']
            del new_obj['bbox_np']
            del new_obj['pcd_color_np']

            self.append(new_obj)
