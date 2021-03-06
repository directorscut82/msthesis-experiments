#!/usr/bin/env python


"""Build an ensemble of CIFAR 100 Keras models."""

import imp
import json
import logging
import os
import sys

from keras.models import load_model
from keras.utils import np_utils


from natsort import natsorted

import numpy as np

from sklearn.model_selection import train_test_split

import yaml

train_keras = imp.load_source('train_keras', "train/train_keras.py")

from train_keras import get_level, flatten_completely, filter_by_class
from train_keras import update_labels
from create_cm import run_model_prediction
logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.DEBUG,
                    stream=sys.stdout)


def make_paths_absolute_suffix(dir_, conf):
    for key in conf.keys():
        if key.endswith("_path"):
            conf[key] = os.path.join(dir_, conf[key])
            conf[key] = os.path.abspath(conf[key])
            # if not os.path.isfile(conf[key]):
            #     logging.error("%s does not exist.", conf[key])
            #     sys.exit(-1)
        if type(conf[key]) is dict:
            conf[key] = make_paths_absolute_suffix(dir_, conf[key])
    return conf


def make_paths_absolute(dir_, conf):
    for i in range(len(conf["models"])):
        conf["models"][i] = os.path.join(dir_, conf["models"][i])
        conf["models"][i] = os.path.abspath(conf["models"][i])
    conf = make_paths_absolute_suffix(dir_, conf)
    return conf


def calculate_cm(y_true, y_pred, n_classes):
    """Calculate confusion matrix."""
    y_true_i = y_true.flatten()
    y_pred_i = y_pred.argmax(1)
    cm = np.zeros((n_classes, n_classes), dtype=np.int)
    for i, j in zip(y_true_i, y_pred_i):
        cm[i][j] += 1
    return cm


def get_bin(x, n=0):
    """
    Get the binary representation of x.

    Parameters
    ----------
    x : int
    n : int
        Minimum number of digits. If x needs less digits in binary, the rest
        is filled with zeros.

    Returns
    -------
    str
    """
    return format(x, 'b').zfill(n)


def main(ensemble_fname, evaluate_training_data):
    # Read YAML file
    artifacts_fname = "{}.json".format(os.path.splitext(ensemble_fname)[0])
    artifacts = {'single_accuracies': {},
                 'ensemble': {}}
    with open(ensemble_fname) as data_file:
        config = yaml.load(data_file)
        config = make_paths_absolute(os.path.dirname(ensemble_fname),
                                     config)
        artifacts['config'] = config

    sys.path.insert(1, os.path.dirname(config['dataset']['script_path']))
    data_module = imp.load_source('data', config['dataset']['script_path'])

    # Load data
    data = data_module.load_data(config)
    X_train = data['x_train']
    X_test = data['x_test']
    y_train = data['y_train']
    y_test = data['y_test']

    X_train = data_module.preprocess(X_train)
    X_test = data_module.preprocess(X_test)

    # load hierarchy, if present
    if 'hierarchy_path' in config['dataset']:
        with open(config['dataset']['hierarchy_path']) as data_file:
            hierarchy = json.load(data_file)
        if 'subset' in config['dataset']:
            remaining_cls = get_level(hierarchy, config['dataset']['subset'])
            logging.info("Remaining classes: {}".format(remaining_cls))
            # Only do this if coarse is False:
            remaining_cls = flatten_completely(remaining_cls)
            data_module.n_classes = len(remaining_cls)
            X_train, y_train = filter_by_class(X_train, y_train, remaining_cls)
            X_test, y_test = filter_by_class(X_test, y_test, remaining_cls)
            old_cli2new_cli = {}
            for new_cli, old_cli in enumerate(remaining_cls):
                old_cli2new_cli[old_cli] = new_cli
            y_train = update_labels(y_train, old_cli2new_cli)
            y_test = update_labels(y_test, old_cli2new_cli)

    n_classes = data_module.n_classes
    logging.info("n_classes={}".format(n_classes))

    X_train, X_val, y_train, y_val = train_test_split(X_train, y_train,
                                                      test_size=0.10,
                                                      random_state=42)

    if evaluate_training_data:
        X_eval = X_train
        y_eval = y_train
        config['evaluate_training_data'] = True
    else:
        X_eval = X_test
        y_eval = y_test

    # Load models
    if 'model' in config:
        imp.load_source('model_module',
                        config['model']['script_path'])
        from model_module import *

    model_names = natsorted(config["models"])
    print("Ensemble of {} models ({})".format(len(model_names), model_names))
    models = []
    for model_path in model_names:
        print("Load model {}...".format(model_path))
        models.append(load_model(model_path))

    # Calculate confusion matrix
    # y_val_i = y_val.flatten()
    y_preds = []
    for model_path, model in zip(model_names, models):
        print("Evaluate model {}...".format(model_path))
        pred = run_model_prediction(model, config, X_train, X_eval, n_classes)
        y_preds.append(pred)

    accuracies = []

    for model_index, y_val_pred in enumerate(y_preds):
        cm = calculate_cm(y_eval, y_val_pred, n_classes)
        acc = sum([cm[i][i] for i in range(n_classes)]) / float(cm.sum()) * 100
        accuracies.append(acc)
        print("Cl #{:>2} ({}): accuracy: {:0.2f}%"
              .format(model_index + 1, model_names[model_index], acc))
        artifacts['single_accuracies'][model_index] = acc

    accuracies = np.array(accuracies)
    artifacts['single_acc'] = {'mean': np.mean(accuracies),
                               'std': np.std(accuracies)}
    print("Mean single acc={:0.2f}% (std={:0.2f})".format(np.mean(accuracies),
                                                          np.std(accuracies)))

    max_acc = 0.0
    for x in range(1, 2**len(y_preds)):
        bitstring = get_bin(x, len(y_preds))
        y_preds_take = [p for p, i in zip(y_preds, bitstring) if i == "1"]
        y_val_pred = sum(y_preds_take) / bitstring.count("1")
        cm = calculate_cm(y_eval, y_val_pred, n_classes)
        acc = sum([cm[i][i] for i in range(n_classes)]) / float(cm.sum())
        if acc > max_acc:
            print("Ensemble Accuracy: {:0.2f}% ({})".format(acc * 100,
                                                            bitstring))
            max_acc = acc
            artifacts['ensemble']['best_ensemble_acc'] = acc * 100
            artifacts['ensemble']['best_ensemble'] = bitstring
        if x == (2**len(y_preds) - 1):
            print("Ensemble Accuracy: {:0.2f}% ({})".format(acc * 100,
                                                            bitstring))
            artifacts['ensemble']['complete_ensemble_acc'] = acc * 100

    Y_eval = np_utils.to_categorical(y_eval, n_classes)
    smoothed_lables = (y_val_pred + Y_eval) / 2
    np.save("smoothed_lables", smoothed_lables)
    with open(artifacts_fname, 'w') as outfile:
        str_ = json.dumps(artifacts,
                          indent=4, sort_keys=True,
                          separators=(',', ': '), ensure_ascii=False)
        outfile.write(str_)


def get_parser():
    """Get parser object for script xy.py."""
    from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
    parser = ArgumentParser(description=__doc__,
                            formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("-f", "--file",
                        dest="ensemble_fname",
                        help="File to describe an ensemble.",
                        metavar="FILE")
    parser.add_argument("--train",
                        action="store_true",
                        dest="evaluate_training_data",
                        default=False,
                        help="Evaluate on the training set")
    return parser


if __name__ == "__main__":
    args = get_parser().parse_args()
    main(args.ensemble_fname, args.evaluate_training_data)
