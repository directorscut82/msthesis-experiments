#!/usr/bin/env python

from __future__ import absolute_import
from keras.datasets.cifar import load_batch
from keras.utils.data_utils import get_file
from keras import backend as K
import numpy as np
import os
from sklearn.model_selection import train_test_split

n_classes = 100
img_rows = 32
img_cols = 32
img_channels = 3

_mean_filename = "cifar-100-mean.npy"


def load_data(label_mode='fine'):
    """
    Load CIFAR100 dataset.

    Parameters
    ----------
    label_mode: one of "fine", "coarse".

    Returns
    -------
    Tuple of Numpy arrays: `(x_train, y_train), (x_test, y_test)`.

    Raises
    ------
    ValueError: in case of invalid `label_mode`.
    """
    if label_mode not in ['fine', 'coarse']:
        raise ValueError('label_mode must be one of "fine" "coarse".')

    dirname = 'cifar-100-python'
    origin = 'http://www.cs.toronto.edu/~kriz/cifar-100-python.tar.gz'
    path = get_file(dirname, origin=origin, untar=True)

    fpath = os.path.join(path, 'train')
    x_train, y_train = load_batch(fpath, label_key=label_mode + '_labels')

    fpath = os.path.join(path, 'test')
    x_test, y_test = load_batch(fpath, label_key=label_mode + '_labels')

    y_train = np.reshape(y_train, (len(y_train), 1))
    y_test = np.reshape(y_test, (len(y_test), 1))

    if K.image_data_format() == 'channels_last':
        x_train = x_train.transpose(0, 2, 3, 1)
        x_test = x_test.transpose(0, 2, 3, 1)

    x_train, x_val, y_train, y_val = train_test_split(x_train, y_train,
                                                      test_size=0.10,
                                                      random_state=42,
                                                      stratify=y_train)

    return {'x_train': x_train, 'y_train': y_train,
            'x_val': x_val, 'y_val': y_val,
            'x_test': x_test, 'y_test': y_test}


def preprocess(x, subtact_mean=False):
    """Preprocess features."""
    x = x.astype('float32')

    if not subtact_mean:
        x /= 255.0
    else:
        dir_path = os.path.dirname(os.path.realpath(__file__))
        mean_path = os.path.join(dir_path, _mean_filename)
        mean_image = np.load(mean_path)
        x -= mean_image
        x /= 128.
    return x


if __name__ == '__main__':
    data = load_data()
    mean_image = np.mean(data['x_train'], axis=0)
    np.save(_mean_filename, mean_image)
    import scipy.misc
    scipy.misc.imshow(mean_image)
