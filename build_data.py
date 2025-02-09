import argparse
import os
import pickle
import random
from typing import List, Sized, Union, Optional, Tuple

import numpy as np
import torch
from torchtext import vocab
from torchtext.data import get_tokenizer

tokenizer = get_tokenizer("basic_english")


def _check_truncate(vec, truncate, truncate_left=False):
    """
    Check that vector is truncated correctly.
    """
    if truncate is None:
        return vec
    if len(vec) <= truncate:
        return vec
    if truncate_left:
        return vec[-truncate:]
    else:
        return vec[:truncate]


def padded_tensor(
    items: List[Union[List[int], torch.LongTensor]],
    pad_idx: int = 0,
    left_padded: bool = False,
    max_len: Optional[int] = None,
) -> Tuple[torch.LongTensor, List[int]]:
    """
    Create a padded matrix from an uneven list of lists.

    Returns (padded, lengths), where padded is the padded matrix, and lengths
    is a list containing the lengths of each row.

    Matrix is right-padded (filled to the right) by default, but can be
    left padded if the flag is set to True.

    Matrix can also be placed on cuda automatically.

    :param list[iter[int]] items: List of items
    :param int pad_idx: the value to use for padding
    :param bool left_padded:
    :param int max_len: if None, the max length is the maximum item length

    :returns: (padded, lengths) tuple
    :rtype: (Tensor[int64], list[int])
    """

    # number of items
    n = len(items)
    # length of each item
    lens: List[int] = [len(item) for item in items]  # type: ignore
    # max in time dimension
    t = max(lens) if max_len is None else max_len

    # if input tensors are empty, we should expand to nulls
    t = max(t, 1)

    if isinstance(items[0], torch.Tensor):
        # keep type of input tensors, they may already be cuda ones
        output = items[0].new(n, t)  # type: ignore
    else:
        output = torch.LongTensor(n, t)  # type: ignore
    output.fill_(pad_idx)

    for i, (item, length) in enumerate(zip(items, lens)):
        if length == 0:
            # skip empty items
            continue
        if not isinstance(item, torch.Tensor):
            # put non-tensors into a tensor
            item = torch.LongTensor(item)  # type: ignore
        if left_padded:
            # place at end
            output[i, t - length:] = item
        else:
            # place at beginning
            output[i, :length] = item

    return output, lens


def padded_3d(
    tensors: List[torch.LongTensor],
    pad_idx: int = 0,
    left_padded: bool = False,
    max_len=None,
    dtype=torch.long,
):
    a = len(tensors)
    b = max(len(row) for row in tensors)  # type: ignore
    c = max(len(item) for row in tensors for item in row) if max_len is None else max_len  # type: ignore

    c = max(c, 1)

    output = torch.full((a, b, c), pad_idx, dtype=dtype)

    for i, row in enumerate(tensors):
        item: Sized
        idx = [i for i in range(row.size(0) - 1, -1, -1)]
        idx = torch.LongTensor(idx)
        for j, item in enumerate(row.index_select(0, idx)):  # type: ignore
            if len(item) == 0:
                continue
            if not isinstance(item, torch.Tensor):
                item = torch.Tensor(item, dtype=dtype)
            if left_padded:
                output[i, -j - 1, c - len(item):] = item
            else:
                output[i, -j - 1, : len(item)] = item

    return output


def build_vocab(lst_of_utterances, min_freq=3, unk_token='<UNK>', pad_token='<PAD>'):
    tok2idx = dict()
    tok2freq = dict()

    for u in lst_of_utterances:
        toks = tokenizer(u)
        for tok in toks:
            if tok not in tok2freq:
                tok2freq[tok] = 1
            else:
                tok2freq[tok] += 1
    idx = 2
    for tok, freq in tok2freq.items():
        if freq >= min_freq:
            tok2idx[tok] = idx
            idx += 1
    tok2idx[pad_token] = 0
    tok2idx[unk_token] = 1
    return tok2idx


def build_embed(built_vocab):
    embs = vocab.GloVe('twitter.27B', dim=200)
    ret_embs = torch.zeros((len(built_vocab), embs.dim))
    for tok, idx in built_vocab.items():
        ret_embs[idx] = embs.get_vecs_by_tokens(tok, lower_case_backup=True)
    return [np.asarray(vec) for vec in ret_embs]


def read_support_dialogues(f_path):
    dialogues = []
    with open(f_path, encoding='utf-8') as f:
        for line in f.readlines():
            
            
            # if not line.islower():
            #     raise RuntimeError('The corpus is not lower-cased!')
            item_arr = line.strip().split('\t')
            
            if len(item_arr) < 2:
                pass
            
            context = [u.strip() for u in item_arr[1:-1]]
            response = item_arr[-1].strip()
            label = int(item_arr[0].strip())
            
            dialogues.append((context, response, label))

    return dialogues


def vectorize_dialogue(dialogues, built_dict):
    utterances = []
    responses = []
    labels = []
    for context, response, label in dialogues:
        utterances.append([_check_truncate(vectorized(tokenizer(u), built_dict), 50, True) for u in context])
        responses.append(_check_truncate(vectorized(tokenizer(response), built_dict), 50))
        labels.append(label)

    return utterances, responses, labels


def vectorized(tok_arr, built_dict):
    return [built_dict.get(t, built_dict.get('<UNK>')) for t in tok_arr]


def dump_data(X_train_utterances, X_train_responses, y_train, f_name):
    X_train_utterances = padded_3d(
        [padded_tensor(utts, max_len=50, left_padded=True)[0] for utts in X_train_utterances],
        max_len=50,
        left_padded=True
    ).tolist()
    X_train_responses = padded_tensor(X_train_responses, max_len=50, left_padded=True)[0].tolist()

    pickle.dump((X_train_utterances, X_train_responses, y_train),
                open(os.path.join(args['out_dir'], f_name), 'wb'))


def main(args):
    train_dialogues = read_support_dialogues(os.path.join(args['data_dir'], "train.txt"))
    print("train")
    print(train_dialogues[:10])
    dev_dialogues = read_support_dialogues(os.path.join(args['data_dir'], "valid.txt"))
    print("valid")
    print(dev_dialogues[:10])
    test_dialogues = read_support_dialogues(os.path.join(args['data_dir'], "test.txt"))
    print("test")
    print(test_dialogues[:10])
    all_utterances = [' '.join(c) + ' ' + r for c, r, _ in train_dialogues + dev_dialogues + test_dialogues]
    built_dict = build_vocab(all_utterances)
    
    print(len(built_dict))
    
    X_train_utterances, X_train_responses, y_train = vectorize_dialogue(train_dialogues, built_dict)
    X_dev_utterances, X_dev_responses, y_dev = vectorize_dialogue(dev_dialogues, built_dict)
    X_test_utterances, X_test_responses, y_test = vectorize_dialogue(test_dialogues, built_dict)
    
    print(X_train_utterances[:10])
    
    dump_data(X_train_utterances, X_train_responses, y_train, 'train.pkl')
    dump_data(X_dev_utterances, X_dev_responses, y_dev, 'dev.pkl')
    dump_data(X_test_utterances, X_test_responses, y_test, 'test.pkl')

    embed = build_embed(built_dict)
    pickle.dump((built_dict, embed), open(os.path.join(args['out_dir'], 'vocab_and_embeddings.pkl'), 'wb'))


def check_args(args):
    if not os.path.exists(args.data_dir):
        raise ValueError("data_dir: {} does not exist!".format(args.data_dir))
    if not os.path.isfile(args.embed_file):
        raise ValueError("embed_file: {} does not exist!".format(args.embed_file))
    if not os.path.exists(args.out_dir):
        os.mkdir(args.out_dir)


args = {}
args['data_dir'] = 'support_data'
args['out_dir'] = 'support_data'
#check_args(args)
main(args)
