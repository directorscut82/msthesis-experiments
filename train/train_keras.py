#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Train a CNN."""

from __future__ import print_function
import csv
import json
import logging
import os
import sys
import collections
from copy import deepcopy
import time
import platform
import datetime
import pickle
import numpy as np
np.random.seed(0)
from keras.preprocessing.image import ImageDataGenerator
from keras import backend as K
from keras.callbacks import ModelCheckpoint, EarlyStopping, TensorBoard
from keras.callbacks import RemoteMonitor, ReduceLROnPlateau, Callback
from keras.utils import np_utils
from keras.models import load_model
from clr_callback import CyclicLR

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.DEBUG,
                    stream=sys.stdout)


class History(Callback):
    """
    Callback that records events into a `History` object.

    This callback is automatically applied to
    every Keras model. The `History` object
    gets returned by the `fit` method of models.
    """

    def on_train_begin(self, logs=None):
        if not hasattr(self, 'epoch'):
            self.epoch = []
            self.history = {}

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        self.epoch.append(epoch)
        for k, v in logs.items():
            self.history.setdefault(k, []).append(v)


def flatten_completely(iterable):
    """Make a flat list out of an interable of iterables of iterables ..."""
    flattened = []
    iterable = deepcopy(iterable)
    queue = [iterable]
    while len(queue) > 0:
        el = queue.pop(0)
        if isinstance(el, collections.Iterable):
            for subel in el[::-1]:
                queue.insert(0, subel)
        else:
            flattened.append(el)
    return flattened


def get_old_cli2new_cli(hierarchy):
    """Get a dict mapping from the old class idx to the new class indices."""
    remaining_cls = flatten_completely(hierarchy)
    old_cli2new_cli = {}
    for new_cli, old_cli in enumerate(remaining_cls):
        old_cli2new_cli[old_cli] = new_cli
    return old_cli2new_cli


def apply_hierarchy(hierarchy, y):
    """Apply a hierarchy to a label vector."""
    oldi2newi = get_old_cli2new_cli(hierarchy)
    for i in range(len(y)):
        y[i] = oldi2newi[y[i][0]]
    return y


def get_level(list_, level):
    """
    Select a part of a nested list_ by level.

    Parameters
    ----------
    list : nested list
    level : list

    Returns
    -------
    list

    Examples
    --------
    >>> list_ = [[0, 1], [2, [3, 4, 5, [6, 7, [8, 9]]]]]
    >>> get_level(list_, [0])
    [0, 1]
    >>> get_level(list_, [1])
    [2, [3, 4, 5, [6, 7, [8, 9]]]]
    >>> get_level(list_, [1, 1, 3])
    [6, 7, [8, 9]]
    """
    level = deepcopy(level)
    if len(level) > 0:
        i = level.pop(0)
        return get_level(list_[i], level)
    else:
        return list_


def filter_by_class(X_old, y_old, remaining_cls):
    """Remove all instances of classes which are not in remaining_cls."""
    X = []
    y = []
    for x_tmp, y_tmp in zip(X_old, y_old):
        if y_tmp in remaining_cls:
            X.append(x_tmp)
            y.append(y_tmp)
    return np.array(X), np.array(y)


def update_labels(y, old_cli2new_cli):
    """Update labels y with a dictionary old_cli2new_cli."""
    for i in range(len(y)):
        y[i][0] = old_cli2new_cli[y[i][0]]
    return y


def get_nonexistant_path(fname_path):
    """
    Get the path to a filename which does not exist by incrementing path.

    Examples
    --------
    >>> get_nonexistant_path('/etc/issue')
    '/etc/issue-1'
    >>> get_nonexistant_path('whatever/1337bla.py')
    'whatever/1337bla.py'
    """
    if not os.path.exists(fname_path):
        return fname_path
    filename, file_extension = os.path.splitext(fname_path)
    i = 1
    new_fname = "{}-{}{}".format(filename, i, file_extension)
    while os.path.exists(new_fname):
        i += 1
        new_fname = "{}-{}{}".format(filename, i, file_extension)
    return new_fname


def handle_hierarchies(config, data_module, X_train, y_train, X_test, y_test,
                       index_file=None):
    """
    Adjust data to hierarchy.

    Parameters
    ----------
    config : dict
    data_module : Python module
    X_train : np.array
    y_train : np.array
    X_test : np.array
    y_test : np.array
    remaining_idx : np.array
        Indices of the test set which should remain

    Returns
    -------
    dict
        Hierarchy
    """
    with open(config['dataset']['hierarchy_path']) as data_file:
        hierarchy = json.load(data_file)
    logging.info("Loaded hierarchy: {}".format(hierarchy))
    if 'subset' in config['dataset']:
        remaining_cls = get_level(hierarchy, config['dataset']['subset'])
        logging.info("Remaining classes: {}".format(remaining_cls))
        # Only do this if coarse is False:
        old_cli2new_cli = get_old_cli2new_cli(remaining_cls)
        remaining_cls = flatten_completely(remaining_cls)
        data_module.n_classes = len(old_cli2new_cli)
        X_train, y_train = filter_by_class(X_train, y_train, remaining_cls)
        if index_file is not None:
            with open(index_file, 'rb') as handle:
                cm_indices = pickle.load(handle)
            remaining_idx = []
            print("Length of index matrix: {}x{}"
                  .format(len(cm_indices), len(cm_indices[0])))
            remaining_cls_n = [flatten_completely(hierarchy).index(c)
                               for c in remaining_cls]
            for i in remaining_cls_n:
                for j in remaining_cls_n:
                    for class_idx in cm_indices[i][j]:
                        remaining_idx.append(class_idx)
            remaining_idx = np.array(remaining_idx)
            print("Remaining indices: {}".format(len(remaining_idx)))

            X_test = X_test[remaining_idx]
            y_test = y_test[remaining_idx]
        else:
            X_test, y_test = filter_by_class(X_test, y_test, remaining_cls)
        y_train = update_labels(y_train, old_cli2new_cli)
        y_test = update_labels(y_test, old_cli2new_cli)
    if config['dataset']['coarse']:
        data_module.n_classes = len(hierarchy)
        print("!" * 80)
        print("this might be wrong!!!!")
        y_train = apply_hierarchy(hierarchy, y_train)
        y_test = apply_hierarchy(hierarchy, y_test)
    return {'hierarchy': hierarchy,
            'X_train': X_train, 'y_train': y_train,
            'X_test': X_test, 'y_test': y_test,
            'remaining_cls': remaining_cls}


def main(data_module, model_module, optimizer_module, filename, config,
         use_val=False):
    """Patch everything together."""
    batch_size = config['train']['batch_size']
    nb_epoch = config['train']['epochs']

    today = datetime.datetime.now()
    datestring = today.strftime('%Y%m%d-%H%M-%S')

    # The data, shuffled and split between train and test sets:
    data = data_module.load_data(config)
    print("Data loaded.")

    X_train, y_train = data['x_train'], data['y_train']
    X_train = data_module.preprocess(X_train)

    # Get use_val value
    if 'use_val' in config['train']:
        use_val = config['train']['use_val']
    else:
        use_val = True

    # Get training / validation sets
    if use_val:
        X_test, y_test = data['x_val'], data['y_val']
    else:
        X_test, y_test = data['x_test'], data['y_test']
        X_val = data_module.preprocess(data['x_val'])
        X_train = np.append(X_train, X_val, axis=0)
        y_train = np.append(y_train, data['y_val'], axis=0)
    X_test = data_module.preprocess(X_test)

    # load hierarchy, if present
    if 'hierarchy_path' in config['dataset']:
        ret = handle_hierarchies(config, data_module,
                                 X_train, y_train, X_test, y_test)
        # hierarchy = ret['hierarchy']
        X_train = ret['X_train']
        y_train = ret['y_train']
        X_test = ret['X_test']
        y_test = ret['y_test']

    nb_classes = data_module.n_classes
    logging.info("# classes = {}".format(data_module.n_classes))
    img_rows = data_module.img_rows
    img_cols = data_module.img_cols
    img_channels = data_module.img_channels
    da = config['train']['data_augmentation']

    # Convert class vectors to binary class matrices.
    Y_train = np_utils.to_categorical(y_train, nb_classes)
    Y_test = np_utils.to_categorical(y_test, nb_classes)
    # Y_train = Y_train.reshape((-1, 1, 1, nb_classes))  # For fcn
    # Y_test = Y_test.reshape((-1, 1, 1, nb_classes))

    if 'smooth_train' in config['dataset']:
        Y_train = np.load(config['dataset']['smooth_train'])

    if 'smooth_test_path' in config['dataset']:
        Y_test = np.load(config['dataset']['smooth_test_path'])

    # Input shape depends on the backend
    if K.image_dim_ordering() == "th":
        input_shape = (img_channels, img_rows, img_cols)
    else:
        input_shape = (img_rows, img_cols, img_channels)

    model = model_module.create_model(nb_classes, input_shape, config)
    print("Model created")

    if 'initializing_model_path' in config['model']:
        init_model_path = config['model']['initializing_model_path']
        if not os.path.isfile(init_model_path):
            logging.error("initializing_model={} not found"
                          .format(init_model_path))
            sys.exit(-1)
        init_model = load_model(init_model_path)
        layer_dict_init = dict([(layer.name, layer)
                                for layer in init_model.layers])
        layer_dict_model = dict([(layer.name, layer)
                                 for layer in model.layers])
        for layer_name in layer_dict_model.keys():
            if layer_name in layer_dict_init:
                print("\tLoad layer weights '{}'".format(layer_name))
                weights = layer_dict_init[layer_name].get_weights()
                try:
                    layer_dict_model[layer_name].set_weights(weights)
                except ValueError:
                    print("\t\twrong shape - skip")
        logging.info("Done initializing")

    model.summary()
    optimizer = optimizer_module.get_optimizer(config)
    model.compile(loss='categorical_crossentropy',
                  optimizer=optimizer,
                  metrics=["accuracy"])
    print("Finished compiling")
    print("Building model...")

    es = EarlyStopping(monitor='val_acc',
                       min_delta=0,
                       patience=10, verbose=1, mode='auto')
    history_cb = History()
    callbacks = [es, history_cb]  # remote,
    if 'checkpoint' in config['train'] and config['train']['checkpoint']:
        checkpoint_fname = os.path.basename(config['train']['artifacts_path'])
        if 'saveall' in config['train'] and config['train']['saveall']:
            checkpoint_fname = ("{}_{}.chk.{{epoch:02d}}.h5"
                                .format(checkpoint_fname, datestring))
            save_best_only = False
        else:
            checkpoint_fname = "{}_{}.chk.h5".format(checkpoint_fname,
                                                     datestring)
            save_best_only = True
        model_chk_path = os.path.join(config['train']['artifacts_path'],
                                      checkpoint_fname)
        model_chk_path = get_nonexistant_path(model_chk_path)
        checkpoint = ModelCheckpoint(model_chk_path,
                                     monitor="val_acc",
                                     save_best_only=save_best_only,
                                     save_weights_only=False)
        callbacks.append(checkpoint)
    if 'tensorboard' in config['train'] and config['train']['tensorboard']:
        tensorboard = TensorBoard(log_dir='./logs', histogram_freq=0,
                                  write_graph=True, write_images=True)
        callbacks.append(tensorboard)
    if 'remote' in config['train'] and config['train']['remote']:
        remote = RemoteMonitor(root='http://localhost:9000')
        callbacks.append(remote)
    if 'lr_reducer' in config['train'] and config['train']['lr_reducer']:
        lr_reducer = ReduceLROnPlateau(monitor='val_acc',
                                       factor=0.3,
                                       cooldown=0,
                                       patience=3,
                                       min_lr=0.5e-6,
                                       verbose=1)
        callbacks.append(lr_reducer)
    if 'clr' in config['train']:
        clr = CyclicLR(base_lr=config['train']['clr']['base_lr'],
                       max_lr=config['train']['clr']['max_lr'],
                       step_size=(config['train']['clr']['step_size'] *
                                  (X_train.shape[0] // batch_size)),
                       mode=config['train']['clr']['mode'])
        callbacks.append(clr)

    if not da:
        print('Not using data augmentation.')
        if 'checkpoint' in config['train'] and config['train']['checkpoint']:
            model.save(model_chk_path.format(epoch=0)
                       .replace('.00.', '.00.a.'))
        t0 = time.time()
        model.fit(X_train, Y_train,
                  batch_size=batch_size,
                  epochs=nb_epoch,
                  validation_data=(X_test, Y_test),
                  shuffle=True,
                  callbacks=callbacks)
        t1 = time.time()
        t2 = t1
        epochs_augmented_training = 0
    else:
        print('Using real-time data augmentation.')

        if 'hue_shift' in da:
            hsv_augmentation = (da['hue_shift'],
                                da['saturation_scale'],
                                da['saturation_shift'],
                                da['value_scale'],
                                da['value_shift'])
        else:
            hsv_augmentation = None

        # This will do preprocessing and realtime data augmentation:
        datagen = ImageDataGenerator(
            # set input mean to 0 over the dataset
            featurewise_center=da['featurewise_center'],
            # set each sample mean to 0
            samplewise_center=da['samplewise_center'],
            # divide inputs by std of the dataset
            featurewise_std_normalization=False,
            # divide each input by its std
            samplewise_std_normalization=da['samplewise_std_normalization'],
            zca_whitening=da['zca_whitening'],
            # randomly rotate images in the range (degrees, 0 to 180)
            rotation_range=da['rotation_range'],
            # randomly shift images horizontally (fraction of total width)
            width_shift_range=da['width_shift_range'],
            # randomly shift images vertically (fraction of total height)
            height_shift_range=da['height_shift_range'],
            horizontal_flip=da['horizontal_flip'],
            vertical_flip=da['vertical_flip'],
            hsv_augmentation=hsv_augmentation,
            zoom_range=da['zoom_range'],
            shear_range=da['shear_range'],
            channel_shift_range=da['channel_shift_range'])

        # Compute quantities required for featurewise normalization
        # (std, mean, and principal components if ZCA whitening is applied).
        datagen.fit(X_train, seed=0)

        # Apply normalization to test data
        for i in range(len(X_test)):
            X_test[i] = datagen.standardize(X_test[i])

        # Fit the model on the batches generated by datagen.flow().
        steps_per_epoch = X_train.shape[0] // batch_size
        if 'checkpoint' in config['train'] and config['train']['checkpoint']:
            model.save(model_chk_path.format(epoch=0).replace('.00.',
                                                              '.00.a.'))
        t0 = time.time()
        model.fit_generator(datagen.flow(X_train, Y_train,
                            batch_size=batch_size),
                            steps_per_epoch=steps_per_epoch,
                            epochs=nb_epoch,
                            validation_data=(X_test, Y_test),
                            callbacks=callbacks)
        t1 = time.time()
        # Train one epoch without augmentation to make sure data distribution
        # is fit well
        loss_history = history_cb.history["loss"]
        epochs_augmented_training = len(loss_history)
        model.fit(X_train, Y_train,
                  batch_size=batch_size,
                  epochs=nb_epoch,
                  validation_data=(X_test, Y_test),
                  shuffle=True,
                  callbacks=callbacks,
                  initial_epoch=len(loss_history))
        t2 = time.time()
    loss_history = history_cb.history["loss"]
    acc_history = history_cb.history["acc"]
    val_acc_history = history_cb.history["val_acc"]
    np_loss_history = np.array(loss_history)
    np_acc_history = np.array(acc_history)
    np_val_acc_history = np.array(val_acc_history)
    history_data = zip(list(range(1, len(np_loss_history) + 1)),
                       np_loss_history, np_acc_history, np_val_acc_history)
    history_data = [(el[0],
                     "%0.4f" % el[1],
                     "%0.4f" % el[2],
                     "%0.4f" % el[3]) for el in history_data]
    history_fname = os.path.basename(config['train']['artifacts_path'])
    history_fname = "{}_{}_history.csv".format(history_fname, datestring)
    csv_path = os.path.join(config['train']['artifacts_path'],
                            history_fname)
    csv_path = get_nonexistant_path(csv_path)
    with open(csv_path, 'w') as fp:
        writer = csv.writer(fp, delimiter=',')
        writer.writerows([("epoch", "loss", "acc", "val_acc")])
        writer.writerows(history_data)
    training_time = t1 - t0
    readjustment_time = t2 - t1
    print("wall-clock training time: {}s".format(training_time))
    model_fn = os.path.basename(config['train']['artifacts_path'])
    model_fn = "{}_{}.h5".format(model_fn, datestring)
    model_fn = os.path.join(config['train']['artifacts_path'], model_fn)
    model_fn = get_nonexistant_path(model_fn)
    model.save(model_fn)
    # Store training meta data
    data = {'training_time': training_time,
            'readjustment_time': readjustment_time,
            'HOST': platform.node(),
            'epochs': len(history_data),
            'epochs_augmented_training': epochs_augmented_training,
            'config': config}
    meta_train_fname = os.path.join(config['train']['artifacts_path'],
                                    "train-meta_{}.json".format(datestring))
    meta_train_fname = get_nonexistant_path(meta_train_fname)
    with open(meta_train_fname, 'w') as outfile:
        str_ = json.dumps(data,
                          indent=4, sort_keys=True,
                          separators=(',', ': '), ensure_ascii=False)
        outfile.write(str_)


if __name__ == '__main__':
    import doctest
    doctest.testmod()
