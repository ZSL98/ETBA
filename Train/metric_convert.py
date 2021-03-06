from typing import OrderedDict
import cv2
import os
import sys
import csv
import json
import copy
import time
import wandb
import logging
import numpy as np
import pandas as pd
import torch
import random
import argparse
import pickle
from typing import Any, Dict, List, Optional, Union
import torchvision.transforms as transforms
# from tensorboardX import SummaryWriter
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import matplotlib.pyplot as plt


################### Import packages for resnet ####################
###################################################################
# resnet_s1 includes post_layers while partial_resnet does not
# resnet_s1 has dual-heads
import torchvision.models as models
from Mytrain.networks import resnet_s1, partial_resnet, ResNetwthMultiExit
import torchvision.datasets as torchvision_datasets


################### Import packages for openseg ###################
###################################################################
# SpatialOCRNet_with_exit has dual-heads, while SpatialOCRNet_with_only_exit has only one exit
from openseg.lib.models.nets.ocrnet_with_exit import SpatialOCRNet_with_only_exit, SpatialOCRNet_with_exit, SpatialOCRNet_with_multi_exit
from openseg.lib.models.nets.ocrnet import SpatialOCRNet
from openseg.lib.utils.tools.configer import Configer
from openseg.lib.datasets.data_loader import DataLoader
from openseg.lib.metrics import running_score as rslib
from openseg.segmentor.tools.data_helper import DataHelper
from openseg.segmentor.tools.evaluator import get_evaluator
from openseg.segmentor.etrainer import ETrainer
from openseg import main


################### Import packages for posenet ###################
###################################################################
# PoseResNetwthExit has dual-heads
from pose_estimation.lib.models.pose_resnet import PoseResNetwthExit, PoseResNetwthOnlyExit
from pose_estimation.lib.core.config import update_config, config, get_model_name
from pose_estimation.lib.core.function import validate_exit
from pose_estimation.lib.models import pose_resnet
from pose_estimation.lib.utils.utils import create_logger
from pose_estimation.lib.core.loss import DistillationBasedLoss, JointsMSELoss
from pose_estimation.lib import dataset
from pose_estimation.lib.utils.transforms import flip_back
from pose_estimation.lib.core.evaluate import accuracy
from pose_estimation.lib.core.inference import get_final_preds
from pose_estimation.lib.utils.vis import save_debug_images


################### Import packages for Bert ######################
###################################################################
from bert_train.modeling_bert import BertWithExit, BertWithExit_s1, BertWithExit_s2, BertWithSinglehead
from transformers.models.bert.modeling_bert import BertForSequenceClassification
from transformers.utils import logging as transformers_logging
from transformers.trainer_utils import get_last_checkpoint
import transformers
import datasets
from dataclasses import dataclass, field
from datasets import load_dataset, load_metric
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    EvalPrediction,
    HfArgumentParser,
    PretrainedConfig,
    Trainer,
    TrainingArguments,
    default_data_collator,
    set_seed,
)

task_to_keys = {
    "cola": ("sentence", None),
    "mnli": ("premise", "hypothesis"),
    "mrpc": ("sentence1", "sentence2"),
    "qnli": ("question", "sentence"),
    "qqp": ("question1", "question2"),
    "rte": ("sentence1", "sentence2"),
    "sst2": ("sentence", None),
    "stsb": ("sentence1", "sentence2"),
    "wnli": ("sentence1", "sentence2"),
}


################### Import packages for Wav2Vec2 ##################
###################################################################
chars_to_ignore_regex = '[\,\?\.\!\-\;\:\"]'
import re
import soundfile as sf
from transformers import Wav2Vec2CTCTokenizer, Wav2Vec2FeatureExtractor, Wav2Vec2Processor, TrainingArguments, Trainer
from Wav2Vec2.wav2vec2_model import Wav2Vec2ForCTC, Wav2Vec2Model, Wav2Vec2PreTrainedModel, Wav2Vec2Config, Wav2Vec2Encoder, Wav2Vec2EncoderLayer
from Wav2Vec2.wav2vec2_model import Wav2Vec2RawEncoder, Wav2Vec2_with_exit

logger = logging.getLogger(__name__)

# For openseg and posenet, the parameters of the dual-head-model 
# are transfered from the ee-head-model and the final-head model. \
# Then I realized there is no need to do the load_state_dict, \
# so I simply use net_wth_eehead and net_wth_finalhead to convert metrics.

def parse_args():
    parser = argparse.ArgumentParser(description='Metric Converter')
    parser.add_argument('--task', type=str, default='cola', help='Task name')
    parser.add_argument('--dataset_name', type=str, default='cola', help='Dataset name')
    parser.add_argument('--mode', type=str, default='test', help='Converter mode')
    parser.add_argument('--metric_thres', type=float, default=99.5, help='Metric threshold')
    parser.add_argument('--init', type=bool, default=False, help='Determine the threshold or not')
    parser.add_argument('--batch_size', type=int, default=4, help='Batch size')
    parser.add_argument('--last_exit', type=int, nargs='+', help='Last exit')
    parser.add_argument('--all_or_sep', type=bool, default=True, help='All or Separate')

    args = parser.parse_args()
    return args

class convert_resnet:
    def __init__(self, split_point, batch_size, last_exit, metric_thres, dataset_used, final_profile=False) -> None:
        super().__init__()
        self.split_point = split_point
        self.p_thres = 0.75
        self.last_exit = last_exit.copy()
        self.exit_sequence = last_exit.copy()
        self.exit_sequence.append(split_point)
        self.batch_size = batch_size
        self.metric_thres = metric_thres
        self.dataset_used = dataset_used
        self.final_profile = final_profile

    def load_complete_resnet(self):
        state_dict = torch.load("/home/slzhang/projects/DeepLearningExamples/PyTorch/Classification/ConvNets/checkpoints/finetune/checkpoint.pth.tar")
        model = ResNetwthMultiExit(exit_list=[1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 33])

        model.load_state_dict(state_dict["state_dict"])
        return model
        
    def load_resnet(self):
        net_wth_finalhead = models.resnet101(pretrained=True)
        # for train sip
        net_wth_eehead_dict = torch.load("/home/slzhang/projects/ETBA/Train/Mytrain/checkpoints/train_sip/checkpoint.pth.tar."+str(self.split_point))
        # net_wth_eehead_dict = torch.load("/home/slzhang/projects/DeepLearningExamples/PyTorch/Classification/ConvNets/checkpoints/train_metric_controlled/split_point_{}/model_best.pth.tar".format(self.split_point))
        net_wth_eehead = partial_resnet(start_point=self.split_point, end_point=self.split_point, simple_exit=False)

        dict_new = OrderedDict()
        for k,v in net_wth_eehead.state_dict().items():
            # for train sip:
            dict_new[k] = net_wth_eehead_dict['state_dict']['module.'+k]
            # dict_new[k] = net_wth_eehead_dict['state_dict'][k]

        net_wth_eehead.load_state_dict(dict_new)

        return net_wth_eehead, net_wth_finalhead

    def eval_resnet(self, net_wth_eehead, net_wth_finalhead):
        if self.dataset_used == 'imagenet':
            valdir = '/home/slzhang/projects/Shallow-Deep-Networks-backup/data/imagenet/ILSVRC/Data/CLS-LOC/val'
        elif self.dataset_used == 'imagenette':
            valdir = '/home/slzhang/projects/Shallow-Deep-Networks-backup/data/imagenette2/val'
        elif self.dataset_used == 'imagewoof':
            valdir = '/home/slzhang/projects/Shallow-Deep-Networks-backup/data/imagewoof2/val'
        normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                        std=[0.229, 0.224, 0.225])
        val_loader = torch.utils.data.DataLoader(
            torchvision_datasets.ImageFolder(valdir, transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                normalize,
            ])),
            batch_size=self.batch_size, shuffle=False,
            num_workers=4, pin_memory=True)

        batch_time = AverageMeter('Time', ':6.3f')
        losses = AverageMeter('Loss', ':.4e')
        top1 = AverageMeter('Acc@1', ':6.2f')
        top5 = AverageMeter('Acc@5', ':6.2f')
        top1_f = AverageMeter('Acc_final@1', ':6.2f')
        top5_f = AverageMeter('Acc_final@5', ':6.2f')
        pass_acc1 = AverageMeter('Acc1@Pass', ':6.2f')
        pass_ratio1 = AverageMeter('Ratio@Pass', ':6.2f')
        moveon_acc1 = AverageMeter('Acc1@Moveon', ':6.2f')
        moveon_ratio1 = AverageMeter('Ratio@Moveon', ':6.2f')
        avg_acc1 = AverageMeter('Acc1@Avg', ':6.2f')

        progress = ProgressMeter(
            len(val_loader),
            [batch_time, pass_acc1, moveon_acc1, moveon_ratio1, avg_acc1],
            prefix='Test: ')

        # switch to evaluate mode
        if self.final_profile == False:
            net_wth_eehead.eval()
            net_wth_finalhead.eval()
            net_wth_eehead = torch.nn.DataParallel(net_wth_eehead).cuda()
            net_wth_finalhead = torch.nn.DataParallel(net_wth_finalhead).cuda()
        else:
            net_wth_eehead.eval()
            net_wth_eehead = torch.nn.DataParallel(net_wth_eehead).cuda()

        criterion = nn.CrossEntropyLoss().cuda()

        with torch.no_grad():
            end = time.time()
            moveon_dict = dict()

            self.hist_data = []
            if len(self.last_exit) == 1:
                last_moveon_dict = dict()
            else:
                with open('./moveon_dict/resnet/{}/resnet_exit_l{}_b{}_t{}.json'.format(self.dataset_used, self.last_exit, self.batch_size, self.metric_thres), 'rb') as f:
                    last_moveon_dict = json.load(f)

            for i, (images, target) in enumerate(val_loader):
                imagenette_map = [0, 217, 482, 491, 497, 566, 569, 571, 574, 701]
                imagewoof_map = [155, 159, 162, 167, 182, 193, 207, 229, 258, 273]
                if self.dataset_used == 'imagenette':
                    for idx in range(len(target)):
                        target[idx] = imagenette_map[target[idx]]
                elif self.dataset_used == 'imagewoof':
                    for idx in range(len(target)):
                        target[idx] = imagewoof_map[target[idx]]

                if len(self.last_exit) == 1:
                    last_moveon_dict[str(i)] = [1]*len(target)

                # compute output
                images = images.cuda()
                target = target.cuda()

                if self.final_profile == False:
                    exit_output = net_wth_eehead(images)
                    output = net_wth_finalhead(images)
                else:
                    outputs = net_wth_eehead(images)
                    exit_output = outputs[int(self.split_point/3)]
                    output = outputs[-1]

                loss = criterion(exit_output, target)

                # measure accuracy and record loss
                matrices = self.validate_resnet(exit_output, output, target, torch.tensor(last_moveon_dict[str(i)], dtype=torch.bool).cuda(), topk=(1, 5))
                acc1 = matrices[0]
                acc5 = matrices[2]
                acc1_final = matrices[1]
                acc5_final = matrices[3]
                p_acc = matrices[4]
                p_ratio = matrices[5]
                m_acc = matrices[6]
                m_ratio = matrices[7]
                moveon_dict[i] = matrices[8].tolist()

                p_acc = p_acc.cuda()
                p_ratio = p_ratio.cuda()
                m_acc = m_acc.cuda()
                m_ratio = m_ratio.cuda()

                losses.update(loss.item(), images.size(0))
                top1.update(acc1[0], images.size(0))
                top5.update(acc5[0], images.size(0))
                top1_f.update(acc1_final[0], images.size(0))
                top5_f.update(acc5_final[0], images.size(0))
                pass_acc1.update(p_acc, images.size(0))
                pass_ratio1.update(p_ratio, images.size(0))
                moveon_acc1.update(m_acc, images.size(0))
                moveon_ratio1.update(m_ratio, images.size(0))
                avg_acc1.update(p_acc*p_ratio+m_acc*m_ratio, images.size(0))

                # measure elapsed time
                batch_time.update(time.time() - end)
                end = time.time()

                if i % 10 == 0:
                    # wandb.log({"acc1": acc1[0], "acc5": acc5[0], "pass_acc": p_acc, "pass_ratio": p_ratio})
                    progress.display(i)

            cnts = plt.hist(self.hist_data, bins=16, range=(0,1))
            print(cnts[0])
            hist_data_numpy = np.array(self.hist_data)

            with open('./moveon_dict/resnet/{}/resnet_exit_l{}_b{}_t{}.json'.format(self.dataset_used, self.exit_sequence, self.batch_size, self.metric_thres), "w+") as f:
                json.dump(moveon_dict, f)

            plt.close()
            print(' * Acc@1 {top1.avg:.3f} Acc@5 {top5.avg:.3f}'
                .format(top1=top1, top5=top5))

        return pass_acc1.avg.cpu().item(), moveon_acc1.avg.cpu().item(), moveon_ratio1.avg.cpu().item(), avg_acc1.avg.cpu().item()

    def validate_resnet(self, output, final_output, target, last_moveon_list, topk=(1,)):
        """Computes the accuracy over the k top predictions for the specified values of k"""
        with torch.no_grad():
            maxk = max(topk)
            batch_size = target.size(0)

            confidence = self.p_thres
            m = nn.Softmax(dim=1)
            softmax_output = m(output)
            softmax_final_output = m(final_output)

            pass_indicator = (torch.max(softmax_output, 1)[0] > confidence) & last_moveon_list
            moveon_indicator = (torch.max(softmax_output, 1)[0] <= confidence) & last_moveon_list
            pass_cnt = sum(pass_indicator)
            moveon_cnt = sum(moveon_indicator)
            correct_indicator = (torch.max(softmax_output, 1)[1] == target) & last_moveon_list
            # final_correct_indicator = torch.max(softmax_final_output + softmax_output, 1)[1] == target
            final_correct_indicator = (torch.max(softmax_final_output, 1)[1] == target) & last_moveon_list
            pass_correct_indicator = pass_indicator & correct_indicator
            moveon_correct_indicator = moveon_indicator & final_correct_indicator
            pass_correct_cnt = sum(pass_correct_indicator)
            moveon_correct_cnt = sum(moveon_correct_indicator)
            # print(str(int(pass_correct_cnt)) + '/' + str(int(pass_cnt)))
            if pass_cnt != 0:
                pass_acc = pass_correct_cnt.float().mul_(100.0 / pass_cnt)
            else:
                pass_acc = torch.tensor(0.0)

            if moveon_cnt != 0:
                moveon_acc = moveon_correct_cnt.float().mul_(100.0 / moveon_cnt)
                tmp = moveon_cnt/sum(last_moveon_list)
                self.hist_data.append(tmp.cpu().item())
            else:
                moveon_acc = torch.tensor(0.0)
                self.hist_data.append(0)

            _, pred = output.topk(maxk, 1, True, True)
            pred = pred.t()
            correct = pred.eq(target.view(1, -1).expand_as(pred))

            _, pred_f = final_output.topk(maxk, 1, True, True)
            pred_f = pred_f.t()
            correct_f = pred_f.eq(target.view(1, -1).expand_as(pred_f))

            res = []
            for k in topk:
                correct_k = correct[:k].reshape(-1).float().sum(0, keepdim=True)
                res.append(correct_k.mul_(100.0 / batch_size))
                correct_f_k = correct_f[:k].reshape(-1).float().sum(0, keepdim=True)
                res.append(correct_f_k.mul_(100.0 / batch_size))            

            res.append(pass_acc)
            if sum(last_moveon_list) == 0:
                res.append(sum(last_moveon_list))
            else:
                res.append(pass_cnt/sum(last_moveon_list))
            res.append(moveon_acc)
            if sum(last_moveon_list) == 0:
                res.append(sum(last_moveon_list))
            else:
                res.append(moveon_cnt/sum(last_moveon_list))
            res.append(moveon_indicator)
            return res

class convert_posenet:
    def __init__(self, split_point, batch_size, last_exit, metric_thres, final_profile=True) -> None:
        super().__init__()
        self.split_point = split_point
        self.p_thres = 0.7
        self.last_exit = last_exit.copy()
        self.exit_sequence = last_exit.copy()
        self.exit_sequence.append(split_point)
        self.batch_size = batch_size
        self.metric_thres = metric_thres
        self.final_profile = final_profile

    def load_final_posenet(self):
        final_model = torch.load("/home/slzhang/projects/ETBA/Train/pose_estimation/checkpoints/finetuned/model_best.pth")
        cfg = "/home/slzhang/projects/ETBA/Train/pose_estimation/experiments/mpii/resnet101/384x384_d256x3_adam_lr1e-3.yaml"
        update_config(cfg)

        # cudnn related setting
        cudnn.benchmark = config.CUDNN.BENCHMARK
        torch.backends.cudnn.deterministic = config.CUDNN.DETERMINISTIC
        torch.backends.cudnn.enabled = config.CUDNN.ENABLED

        net_wth_multi_heads = eval(config.MODEL.NAME+'.get_pose_net_with_multi_exit')(
            config, is_train=True, exit_list=[1,4,7,10,13,16,19,22,25,28,31,33]
        )

        dict_multihead = OrderedDict()
        for k,v in net_wth_multi_heads.state_dict().items():
            dict_multihead[k] = final_model['module.'+k]

        net_wth_multi_heads.load_state_dict(dict_multihead)
        return net_wth_multi_heads


    def load_posenet(self):
        net_wth_finalhead = torch.load("/home/slzhang/projects/ETBA/Train/pose_estimation/checkpoints/pose_resnet_101_384x384.pth.tar")
        net_wth_eehead = torch.load("/home/slzhang/projects/ETBA/Train/pose_estimation/checkpoints/split_point_{}/model_best.pth".format(self.split_point))

        # for k,v in net_wth_eehead['state_dict'].items():
        #     print(k)

        cfg = "/home/slzhang/projects/ETBA/Train/pose_estimation/experiments/mpii/resnet101/384x384_d256x3_adam_lr1e-3.yaml"
        update_config(cfg)

        # cudnn related setting
        cudnn.benchmark = config.CUDNN.BENCHMARK
        torch.backends.cudnn.deterministic = config.CUDNN.DETERMINISTIC
        torch.backends.cudnn.enabled = config.CUDNN.ENABLED

        net_wth_dualheads = eval(config.MODEL.NAME+'.get_pose_net_with_exit')(
            config, is_train=True, start_point = self.split_point
        )

        dict_finalhead = net_wth_finalhead.copy()
        dict_finalhead_keys = list(net_wth_finalhead.keys())
        dict_eehead = net_wth_eehead.copy()
        dict_dualhead = OrderedDict()

        i = 0
        for k,v in net_wth_dualheads.state_dict().items():
            if 'num_batches_tracked' not in k and 'deconv' not in k and 'final' not in k and 'exit' not in k:
                dict_dualhead[k] = dict_finalhead[dict_finalhead_keys[i]]
                i = i + 1

        for k,v in net_wth_dualheads.state_dict().items():
            if 'num_batches_tracked' not in k:
                if 'exit' in k:
                    dict_dualhead[k] = dict_eehead['module.'+k]
                elif 'head' in k:
                    dict_dualhead[k] = dict_eehead['module.'+k[5:]]
                elif 'backbone_s1' not in k:
                    dict_dualhead[k] = dict_finalhead[k]

        net_wth_dualheads.load_state_dict(dict_dualhead)
        return net_wth_dualheads

    def eval_posenet(self):
        if not self.final_profile:
            self.net = self.load_posenet()
        else:
            self.net = self.load_final_posenet()
        self.net = self.net.cuda()
        self.net.eval()

        # logger, final_output_dir, tb_log_dir = create_logger(
        # config, "/home/slzhang/projects/ETBA/Train/pose_estimation/experiments/mpii/resnet101/384x384_d256x3_adam_lr1e-3.yaml", 'train')

        gpus = [int(i) for i in config.GPUS.split(',')]
        self.net = torch.nn.DataParallel(self.net, device_ids=gpus).cuda()
        normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                        std=[0.229, 0.224, 0.225])
        self.valid_dataset = eval('dataset.'+config.DATASET.DATASET)(
            config,
            config.DATASET.ROOT,
            config.DATASET.TEST_SET,
            False,
            transforms.Compose([
                transforms.ToTensor(),
                normalize,
            ])
        )
        self.valid_loader = torch.utils.data.DataLoader(
            self.valid_dataset,
            # batch_size=config.TEST.BATCH_SIZE*len(gpus),
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=config.WORKERS,
            pin_memory=True
        )

        self.criterion = JointsMSELoss(
            use_target_weight=config.LOSS.USE_TARGET_WEIGHT
        ).cuda()

        acc_pass, acc_moveon, moveon_ratio, metric_avg = self.validate_posenet(config)

        return acc_pass, acc_moveon, moveon_ratio, metric_avg

    def validate_posenet(self, config, output_dir=None, writer_dict=None):
        batch_time = AverageMeter('batch_time', ':6.2f')
        losses = AverageMeter('losses', ':6.2f')
        acc = AverageMeter('acc', ':6.2f')
        acc_pass = AverageMeter('acc@Pass', ':6.2f')
        acc_moveon = AverageMeter('acc@Moveon', ':6.2f')
        moveon_ratio = AverageMeter('Ratio@Pass', ':6.2f')

        # switch to evaluate mode
        self.net.eval()

        num_samples = len(self.valid_dataset)
        all_preds = np.zeros((num_samples, config.MODEL.NUM_JOINTS, 3),
                            dtype=np.float32)
        all_boxes = np.zeros((num_samples, 6))
        image_path = []
        filenames = []
        imgnums = []
        idx = 0
        with torch.no_grad():
            end = time.time()
            moveon_dict = dict()
            hist_data = []
            if len(self.last_exit) == 1:
                last_moveon_dict = dict()
            else:
                with open('./moveon_dict/posenet/posenet_train{}_l{}_b{}_t{}.json'.format('all' if self.final_profile else 'sep', self.last_exit, self.batch_size, self.metric_thres), 'rb') as f:
                    last_moveon_dict = json.load(f)

            for i, (input, target, target_weight, meta) in enumerate(self.valid_loader):
                # compute output
                if len(self.last_exit) == 1:
                    last_moveon_dict[str(i)] = [1]*len(target)

                moveon_dict[i] = []
                # Shit......why not compatible
                if not self.final_profile:
                    output, exit_output = self.net(input)
                else:
                    output = self.net(input)
                    exit_output = output[int(self.split_point/3)]
                    output = output[-1]
                if config.TEST.FLIP_TEST:
                    # this part is ugly, because pytorch has not supported negative index
                    # input_flipped = model(input[:, :, :, ::-1])
                    input_flipped = np.flip(input.cpu().numpy(), 3).copy()
                    input_flipped = torch.from_numpy(input_flipped).cuda()
                    output_flipped, exit_output_flipped = self.net(input_flipped)
                    output_flipped = flip_back(output_flipped.cpu().numpy(),
                                            self.valid_dataset.flip_pairs)
                    output_flipped = torch.from_numpy(output_flipped.copy()).cuda()
                    exit_output_flipped = flip_back(exit_output_flipped.cpu().numpy(),
                                            self.valid_dataset.flip_pairs)
                    exit_output_flipped = torch.from_numpy(exit_output_flipped.copy()).cuda()

                    # feature is not aligned, shift flipped heatmap for higher accuracy
                    if config.TEST.SHIFT_HEATMAP:
                        output_flipped[:, :, :, 1:] = \
                            output_flipped.clone()[:, :, :, 0:-1]
                        exit_output_flipped[:, :, :, 1:] = \
                            exit_output_flipped.clone()[:, :, :, 0:-1]
                        # exit_output_flipped[:, :, :, 0] = 0

                    output = (output + output_flipped) * 0.5
                    exit_output = (exit_output + exit_output_flipped) * 0.5

                target = target.cuda(non_blocking=True)
                target_weight = target_weight.cuda(non_blocking=True)

                pixel_confidence = self.p_thres
                num_threshold = self.n_thres
                for j in range(len(output)):
                    if last_moveon_dict[str(i)][j] == 1:
                        if len(exit_output[j][exit_output[j] > pixel_confidence]) > num_threshold:
                            moveon_dict[i].append(0)
                            moveon_ratio.update(0, 1)
                            _, avg_acc, cnt, pred = accuracy(exit_output[j].unsqueeze(0).cpu().numpy(),
                                                target[j].unsqueeze(0).cpu().numpy())
                            acc_pass.update(avg_acc, 1)
                        else:
                            moveon_dict[i].append(1)
                            moveon_ratio.update(1, 1)
                            # exit_output[j] = output[j]
                            _, avg_acc, cnt, pred = accuracy(output[j].unsqueeze(0).cpu().numpy(),
                                                target[j].unsqueeze(0).cpu().numpy())
                            acc_moveon.update(avg_acc, 1)
                        acc.update(avg_acc, 1)
                    else:
                        moveon_dict[i].append(0)

                if sum(last_moveon_dict[str(i)]) > 0:
                    hist_data.append(sum(moveon_dict[i])/sum(last_moveon_dict[str(i)]))
                else:
                    hist_data.append(0)
                # hist_data.append(sum(moveon_dict[i])/len(moveon_dict[i]))
                # for j in range(output.shape[0]):
                #     if sorted(exit_output[j])[-num_threshold] > pixel_confidence:
                #         moveon_ratio.update(0, 1)
                #     else:
                #         moveon_ratio.update(1, 1)
                #         exit_output[j] = output[j]                        

                loss = self.criterion(exit_output, target, target_weight)

                num_images = input.size(0)
                # measure accuracy and record loss
                losses.update(loss.item(), num_images)
                # _, avg_acc, cnt, pred = accuracy(exit_output.cpu().numpy(),
                #                                 target.cpu().numpy())

                # prefix = '{}_{}'.format(os.path.join(output_dir, 'test'), 0)
                # save_debug_images_with_exit(config, input, meta, target, pred*4, 
                #                             output, exit_output, prefix)
                # exit()

                # acc.update(avg_acc, cnt)

                # measure elapsed time
                batch_time.update(time.time() - end)
                end = time.time()

                c = meta['center'].numpy()
                s = meta['scale'].numpy()
                score = meta['score'].numpy()

                preds, maxvals = get_final_preds(
                    config, exit_output.clone().cpu().numpy(), c, s)

                all_preds[idx:idx + num_images, :, 0:2] = preds[:, :, 0:2]
                all_preds[idx:idx + num_images, :, 2:3] = maxvals
                # double check this all_boxes parts
                all_boxes[idx:idx + num_images, 0:2] = c[:, 0:2]
                all_boxes[idx:idx + num_images, 2:4] = s[:, 0:2]
                all_boxes[idx:idx + num_images, 4] = np.prod(s*200, 1)
                all_boxes[idx:idx + num_images, 5] = score
                image_path.extend(meta['image'])
                if config.DATASET.DATASET == 'posetrack':
                    filenames.extend(meta['filename'])
                    imgnums.extend(meta['imgnum'].numpy())

                idx += num_images

                # if i % config.PRINT_FREQ == 0:
                if i % 10 == 0:
                    # wandb.log({"acc":acc, "loss":loss})
                    # msg = 'Test: [{0}/{1}]\t' \
                    #     'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t' \
                    #     'Loss {loss.val:.4f} ({loss.avg:.4f})\t' \
                    #     'Accuracy {acc.val:.3f} ({acc.avg:.3f})\t' \
                    #     'Moveon_Ratio {moveon_ratio.val:.3f} ({moveon_ratio.avg:.3f})'.format(
                    #         i, len(self.valid_loader), batch_time=batch_time,
                    #         loss=losses, acc=acc, moveon_ratio=moveon_ratio)
                    print('acc@Pass: {:.3f}\t acc@Moveon: {:.3f}\t Moveon@Ratio: {:.3f}\t acc: {:.3f}'.format(acc_pass.avg, acc_moveon.avg, moveon_ratio.avg, acc.avg))
                    # logger.info(msg)

                    # prefix = '{}_{}'.format(os.path.join(output_dir, 'val'), i)
                    # save_debug_images(config, input, meta, target, pred*4, exit_output,
                    #                   prefix)

            cnts = plt.hist(hist_data, bins=16, range=(0,1))
            print(cnts[0])

            with open('./moveon_dict/posenet/posenet_train{}_l{}_b{}_t{}.json'.format('all' if self.final_profile else 'sep', self.exit_sequence, self.batch_size, self.metric_thres), "w+") as f:
                    json.dump(moveon_dict, f)          

            # name_values, perf_indicator = self.valid_dataset.evaluate(
            #     config, all_preds, output_dir, all_boxes, image_path,
            #     filenames, imgnums)

            # _, full_arch_name = get_model_name(config)
            # if isinstance(name_values, list):
            #     for name_value in name_values:
            #         _print_name_value(name_value, full_arch_name)
            # else:
            #     _print_name_value(name_values, full_arch_name)

        return acc_pass.avg, acc_moveon.avg, moveon_ratio.avg, acc.avg


class convert_openseg:
    def __init__(self, split_point, batch_size, last_exit, metric_thres, final_profile=False) -> None:
        super().__init__()
        self.split_point = split_point
        self.p_thres = 0.75
        self.n_thres = 30
        self.last_exit = last_exit.copy()
        self.exit_sequence = last_exit.copy()
        self.exit_sequence.append(split_point)
        self.batch_size = batch_size
        self.metric_thres = metric_thres
        self.final_profile = final_profile

    def load_final_openseg(self):
        final_model = torch.load("/home/slzhang/projects/ETBA/Train/openseg/checkpoints/cityscapes_finetuned_new/split_point_888/ocrnet_resnet101_s888_max_performance.pth")
        # final_model = torch.load("/home/slzhang/projects/ETBA/Train/openseg/checkpoints/cityscapes_finetuned_new/split_point_888/ocrnet_resnet101_s888_iters6000.pth")
        config = Configer(configs="/home/slzhang/projects/ETBA/Train/openseg/configs/cityscapes/R_101_D_8_with_exit.json")
        net_wth_multi_heads = SpatialOCRNet_with_multi_exit(config)

        dict_multihead = OrderedDict()
        for k,v in net_wth_multi_heads.state_dict().items():
            dict_multihead[k] = final_model['state_dict']['module.'+k]

        net_wth_multi_heads.load_state_dict(dict_multihead)

        net_wth_finalhead = SpatialOCRNet(config)
        dict_finalhead = torch.load("/home/slzhang/projects/ETBA/Train/openseg/checkpoints/spatial_ocrnet_deepbase_resnet101_dilated8_1_latest.pth")
        dict_finalhead_new = OrderedDict()
        for k,v in net_wth_finalhead.state_dict().items():
            if 'num_batches_tracked' not in k:
                dict_finalhead_new[k] = dict_finalhead['state_dict']['module.'+k]
            
        net_wth_finalhead.load_state_dict(dict_finalhead_new)

        return net_wth_multi_heads, net_wth_finalhead


    def load_openseg(self):
        # load the backbone of the network with dual-heads

        net_wth_finalhead = torch.load("/home/slzhang/projects/ETBA/Train/openseg/checkpoints/spatial_ocrnet_deepbase_resnet101_dilated8_1_latest.pth")
        # for k,v in net_wth_finalhead['state_dict'].items():
        #     print(k)

        config = Configer(configs="/home/slzhang/projects/ETBA/Train/openseg/configs/cityscapes/R_101_D_8_with_exit.json")
        config.update(["network", "split_point"], split_point)
        net_wth_eehead = torch.load("/home/slzhang/projects/ETBA/Train/openseg/checkpoints/cityscapes_metric_controlled/split_point_{}/ocrnet_resnet101_s{}_max_performance.pth".format(split_point, split_point))
        # for k,v in net_wth_eehead['state_dict'].items():
        #     print(k)

        net_wth_dualheads = SpatialOCRNet_with_exit(config)
        # for k,v in net_wth_dualheads.state_dict().items():
        #     print(k)

        dict_finalhead = net_wth_finalhead['state_dict'].copy()
        dict_eehead = net_wth_eehead['state_dict'].copy()
        dict_dualhead = OrderedDict()

        for k,v in net_wth_dualheads.state_dict().items():
            if 'num_batches_tracked' not in k:
                if 'backbone_s1.resinit' in k:
                    dict_dualhead[k] = dict_finalhead['module.backbone'+k[11:]]
                elif 'backbone_s1.pre' in k:
                    dict_dualhead[k] = dict_finalhead['module.backbone.'+k[16:]]
                elif 'backbone_s1.exit' in k:
                    dict_dualhead[k] = dict_eehead['module.'+k]
                elif 'backbone_s2.layer3' in k:
                    new_idx = int(k.split('.')[2]) + config.get("network", "split_point")-7
                    dict_dualhead[k] = dict_finalhead['module.backbone.layer3.'+str(new_idx)+'.'+'.'.join(k.split('.')[3:])]
                elif 'backbone_s2.layer4' in k:
                    dict_dualhead[k] = dict_finalhead['module.backbone.'+k[12:]]
                elif 'conv_3x3_s1' in k:
                    dict_dualhead[k] = dict_eehead['module.conv_3x3' + k[11:]]
                elif 'conv_3x3_s2' in k:
                    dict_dualhead[k] = dict_finalhead['module.conv_3x3' + k[11:]]
                elif 'head_s1' in k:
                    dict_dualhead[k] = dict_eehead['module.'+k.split('.')[0][:-3]+'.'+'.'.join(k.split('.')[1:])]
                elif 'head_s2' in k:
                    dict_dualhead[k] = dict_finalhead['module.'+k.split('.')[0][:-3]+'.'+'.'.join(k.split('.')[1:])]     

        net_wth_dualheads.load_state_dict(dict_dualhead)
        return net_wth_dualheads

    def eval_openseg(self):
        if not self.final_profile:
            net = self.load_openseg()
        else:
            net, net_with_finalhead = self.load_final_openseg()
            # net_with_finalhead = net_with_finalhead.cuda()
            # net_with_finalhead.eval()
        net = net.cuda()
        net.eval()
        config = Configer(configs="/home/slzhang/projects/ETBA/Train/openseg/configs/cityscapes/R_101_D_8_with_exit.json")
        abs_data_dir = "/home/slzhang/projects/ETBA/Train/openseg/data/cityscapes"
        config.update(["val", "batch_size"], self.batch_size)
        config.update(["data", "data_dir"], abs_data_dir)
        config.add(["gpu"], [0, 1, 2, 3])
        config.add(["network", "gathered"], "n")
        config.add(["network", "resume"], None)
        config.add(["optim", "group_method"], None)
        config.add(["data", "include_val"], False)
        config.add(["data", "include_coarse"], False)
        config.add(["data", "include_atr"], False)
        config.add(["data", "only_coarse"], False)
        config.add(["data", "only_mapillary"], False)
        config.add(["data", "drop_last"], True)
        config.add(["network", "loss_balance"], False)
        data_loader = DataLoader(config)
        etrainer = ETrainer(config)
        data_helper = DataHelper(config, etrainer)
        val_loader = data_loader.get_valloader()
        evaluator = get_evaluator(config, etrainer)

        self.moveon_ratio = AverageMeter('Ratio@Pass', ':6.2f')
        self.mIoU = AverageMeter('mIoU@Avg', ':6.2f')
        self.mIoU_s1 = AverageMeter('mIoU_s1@Avg', ':6.2f')
        self.mIoU_s2 = AverageMeter('mIoU_s2@Avg', ':6.2f')

        moveon_dict = dict()
        self.hist_data = []
        if len(self.last_exit) == 1:
            last_moveon_dict = dict()
        else:
            with open('./moveon_dict/openseg/openseg_train{}_l{}_b{}_t{}.json'.format('all' if self.final_profile else 'sep', self.last_exit, self.batch_size, self.metric_thres), 'rb') as f:
                last_moveon_dict = json.load(f)

        for i, data_dict in enumerate(val_loader):
            (inputs, targets), batch_size = data_helper.prepare_data(data_dict)
            moveon_dict[i] = []
            if len(self.last_exit) == 1:
                last_moveon_dict[str(i)] = [1]*len(targets)

            with torch.no_grad():
                if not self.final_profile:
                    outputs = net(*inputs)
                else:
                    outputs_1 = net(*inputs)
                    # outputs_2 = net_with_finalhead(*inputs)
                    exit_place = int((self.split_point-10)/3)
                    outputs = [outputs_1[exit_place][0], outputs_1[exit_place][1], outputs_1[-1][0], outputs_1[-1][1]]
                    # outputs = outputs[]
                if isinstance(outputs, torch.Tensor):
                    outputs = [outputs]
                metas = data_dict["meta"]
                
                for j in range(outputs[1].shape[0]):
                    if last_moveon_dict[str(i)][j] == 1:
                        output_s1 = outputs[1].permute(0, 2, 3, 1)[j].cpu().numpy()
                        output_s2 = outputs[3].permute(0, 2, 3, 1)[j].cpu().numpy()
                        final_output = self.validate_openseg(i, output_s1, output_s2)

                        labelmap = np.argmax(final_output, axis=-1)
                        ori_target = metas[j]['ori_target']
                        RunningScore = rslib.RunningScore(config)
                        RunningScore.update(labelmap[None], ori_target[None])
                        rs = RunningScore.get_mean_iou()
                        if self.moveon_ratio.val == 0:
                            self.mIoU_s1.update(rs)
                            moveon_dict[i].append(0)
                        else:
                            self.mIoU_s2.update(rs)
                            moveon_dict[i].append(1)
                        self.mIoU.update(rs)
                    else:
                        moveon_dict[i].append(0)

            if i % 10 == 0:
                print(str(i) + '/' + str(len(val_loader)) + '  mIoU_s1: {:.3f}\t mIoU_s2: {:.3f}\t Moveon@Ratio: {:.3f}\t mIoU: {:.3f}'.format \
                        (self.mIoU_s1.avg, self.mIoU_s2.avg, self.moveon_ratio.avg, self.mIoU.avg))
                # os.system("clear")
                # print("mIoU: {}".format(mIoU.avg))
                # print("mIoU_s1: {}".format(mIoU_s1.avg))
                # print("mIoU_s2: {}".format(mIoU_s2.avg))
                # print("moveon_ratio: {}".format(self.moveon_ratio.avg))

            if sum(last_moveon_dict[str(i)]) > 0:
                self.hist_data.append(sum(moveon_dict[i])/sum(last_moveon_dict[str(i)]))
            else:
                self.hist_data.append(0)

        cnts = plt.hist(self.hist_data, bins=16, range=(0,1))
        print(cnts[0])

        with open('./moveon_dict/openseg/openseg_train{}_l{}_b{}_t{}.json'.format('all' if self.final_profile else 'sep', self.split_point, self.batch_size, self.metric_thres), "w+") as f:
            json.dump(moveon_dict, f)

        plt.close()

        return self.mIoU_s1.avg, self.mIoU_s2.avg, self.moveon_ratio.avg, self.mIoU.avg

    def validate_openseg(self, idx, output_s1, output_s2):
        # Shape of output_s1/output_s2: (1024, 2048, 19)
        pixel_threshold = self.p_thres
        num_threshold = self.n_thres
        pixel_confidence = np.amax(output_s1, axis=-1)
        # print(pixel_confidence)
        pixel_over_threshold = pixel_confidence > pixel_threshold
        num_pixel_over_threshold = pixel_over_threshold.sum()
        if num_pixel_over_threshold > num_threshold:
            self.moveon_ratio.update(0, 1)
            return output_s1
        else:
            self.moveon_ratio.update(1, 1)
            return output_s2

class convert_bert:
    def __init__(self, split_point, task_name, batch_size, last_exit, metric_thres) -> None:
        super().__init__()
        self.task_name = task_name
        self.last_exit = last_exit.copy()
        self.exit_sequence = last_exit.copy()
        self.exit_sequence.append(split_point)
        self.batch_size = batch_size
        self.split_point = split_point
        self.raw_datasets = load_dataset("glue", task_name, cache_dir=None)
        self.is_regression = task_name == "stsb"
        if not self.is_regression:
            self.label_list = self.raw_datasets["train"].features["label"].names
            self.num_labels = len(self.label_list)
        else:
            self.num_labels = 1

        self.p_thres = 0.8
        self.metric_thres = metric_thres

    def load_bert(self):

        # net_wth_finalhead_dict = torch.load("/home/slzhang/projects/ETBA/Train/bert_train/models/"+self.task_name+'/exit12/pytorch_model.bin')
        # net_wth_eehead_dict = torch.load("/home/slzhang/projects/ETBA/Train/bert_train/models/"+self.task_name+'/exit'+str(self.split_point)+'/pytorch_model.bin')
        finetuned_net = torch.load("/home/slzhang/projects/ETBA/Train/bert/tmp/model/glue/{}/debug/latest/pytorch_model.bin".format(self.task_name))

        config = AutoConfig.from_pretrained(
            'bert-base-uncased',
            num_labels=self.num_labels,
            finetuning_task=self.task_name,
        )
        net_wth_eehead = BertWithSinglehead.from_pretrained('bert-base-uncased', config=config)
        net_wth_eehead.add_exit(self.split_point)
        net_wth_finalhead = BertWithSinglehead.from_pretrained('bert-base-uncased', config=config)
        net_wth_finalhead.add_exit(12)

        dict_eehead = OrderedDict()
        dict_finalhead = OrderedDict()

        for k,v in net_wth_eehead.state_dict().items():
            if 'encoder' in k or 'embeddings' in k:
                dict_eehead[k] = finetuned_net['bert'+k[7:]]
            elif 'pooler' in k:
                dict_eehead[k] = finetuned_net['pooler.'+str(self.split_point-1)+k[14:]]
            else:
                dict_eehead[k] = finetuned_net['classifier.'+str(self.split_point-1)+k[13:]]
        net_wth_eehead.load_state_dict(dict_eehead)

        for k,v in net_wth_finalhead.state_dict().items():
            if 'encoder' in k or 'embeddings' in k:
                dict_finalhead[k] = finetuned_net['bert'+k[7:]]
            elif 'pooler' in k:
                dict_finalhead[k] = finetuned_net['pooler.11'+k[14:]]
            else:
                dict_finalhead[k] = finetuned_net['classifier.11'+k[13:]]
        net_wth_finalhead.load_state_dict(dict_finalhead)

        eval_eehead = self.bert_aux(net_wth_eehead)
        eval_finalhead = self.bert_aux(net_wth_finalhead)

        return eval_eehead, eval_finalhead

    def bert_aux(self, model):
        # See all possible arguments in src/transformers/training_args.py
        # or by passing the --help flag to this script.
        # We now keep distinct sets of args, for a cleaner separation of concerns.
        
        # TODO: rewrite the parser

        # TrainingArguments.per_gpu_eval_batch_size = self.batch_size
        parser = HfArgumentParser((ModelArguments, DataTrainingArguments, TrainingArguments))
        if len(sys.argv) == 2 and sys.argv[1].endswith(".json"):
            # If we pass only one argument to the script and it's the path to a json file,
            # let's parse it to get our arguments.
            model_args, data_args, training_args = parser.parse_json_file(json_file=os.path.abspath(sys.argv[1]))
        else:
            model_args, data_args, training_args = parser.parse_args_into_dataclasses()

        # Setup logging
        logging.basicConfig(
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%m/%d/%Y %H:%M:%S",
            handlers=[logging.StreamHandler(sys.stdout)],
        )

        log_level = training_args.get_process_log_level()
        logger.setLevel(log_level)
        datasets.utils.logging.set_verbosity(log_level)
        transformers.utils.logging.set_verbosity(log_level)
        transformers.utils.logging.enable_default_handler()
        transformers.utils.logging.enable_explicit_format()

        # Log on each process the small summary:
        logger.warning(
            f"Process rank: {training_args.local_rank}, device: {training_args.device}, n_gpu: {training_args.n_gpu}"
            + f"distributed training: {bool(training_args.local_rank != -1)}, 16-bits training: {training_args.fp16}"
        )
        logger.info(f"Training/evaluation parameters {training_args}")

        # Detecting last checkpoint.
        last_checkpoint = None
        if os.path.isdir(training_args.output_dir) and training_args.do_train and not training_args.overwrite_output_dir:
            last_checkpoint = get_last_checkpoint(training_args.output_dir)
            if last_checkpoint is None and len(os.listdir(training_args.output_dir)) > 0:
                raise ValueError(
                    f"Output directory ({training_args.output_dir}) already exists and is not empty. "
                    "Use --overwrite_output_dir to overcome."
                )
            elif last_checkpoint is not None and training_args.resume_from_checkpoint is None:
                logger.info(
                    f"Checkpoint detected, resuming training at {last_checkpoint}. To avoid this behavior, change "
                    "the `--output_dir` or add `--overwrite_output_dir` to train from scratch."
                )

        # Set seed before initializing model.
        set_seed(training_args.seed)

        # Load pretrained model and tokenizer
        #
        # In distributed training, the .from_pretrained methods guarantee that only one local process can concurrently
        # download model & vocab.
        config = AutoConfig.from_pretrained(
            model_args.config_name if model_args.config_name else model_args.model_name_or_path,
            num_labels=self.num_labels,
            finetuning_task=self.task_name,
            cache_dir=model_args.cache_dir,
            revision=model_args.model_revision,
            use_auth_token=True if model_args.use_auth_token else None,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            model_args.tokenizer_name if model_args.tokenizer_name else model_args.model_name_or_path,
            cache_dir=model_args.cache_dir,
            use_fast=model_args.use_fast_tokenizer,
            revision=model_args.model_revision,
            use_auth_token=True if model_args.use_auth_token else None,
        )

        # Preprocessing the raw_datasets
        if self.task_name is not None:
            sentence1_key, sentence2_key = task_to_keys[self.task_name]
        else:
            # Again, we try to have some nice defaults but don't hesitate to tweak to your use case.
            non_label_column_names = [name for name in self.raw_datasets["train"].column_names if name != "label"]
            if "sentence1" in non_label_column_names and "sentence2" in non_label_column_names:
                sentence1_key, sentence2_key = "sentence1", "sentence2"
            else:
                if len(non_label_column_names) >= 2:
                    sentence1_key, sentence2_key = non_label_column_names[:2]
                else:
                    sentence1_key, sentence2_key = non_label_column_names[0], None

        # Padding strategy
        if data_args.pad_to_max_length:
            padding = "max_length"
        else:
            # We will pad later, dynamically at batch creation, to the max sequence length in each batch
            padding = False

        # Some models have set the order of the labels to use, so let's make sure we do use it.
        label_to_id = None
        if (
            model.config.label2id != PretrainedConfig(num_labels=self.num_labels).label2id
            and self.task_name is not None
            and not self.is_regression
        ):
            # Some have all caps in their config, some don't.
            label_name_to_id = {k.lower(): v for k, v in model.config.label2id.items()}
            if list(sorted(label_name_to_id.keys())) == list(sorted(self.label_list)):
                label_to_id = {i: int(label_name_to_id[self.label_list[i]]) for i in range(self.num_labels)}
            else:
                logger.warning(
                    "Your model seems to have been trained with labels, but they don't match the dataset: ",
                    f"model labels: {list(sorted(label_name_to_id.keys()))}, dataset labels: {list(sorted(self.label_list))}."
                    "\nIgnoring the model labels as a result.",
                )
        elif self.task_name is None and not self.is_regression:
            label_to_id = {v: i for i, v in enumerate(self.label_list)}

        if label_to_id is not None:
            model.config.label2id = label_to_id
            model.config.id2label = {id: label for label, id in config.label2id.items()}
        elif self.task_name is not None and not self.is_regression:
            model.config.label2id = {l: i for i, l in enumerate(self.label_list)}
            model.config.id2label = {id: label for label, id in config.label2id.items()}

        if data_args.max_seq_length > tokenizer.model_max_length:
            logger.warning(
                f"The max_seq_length passed ({data_args.max_seq_length}) is larger than the maximum length for the"
                f"model ({tokenizer.model_max_length}). Using max_seq_length={tokenizer.model_max_length}."
            )
        max_seq_length = min(data_args.max_seq_length, tokenizer.model_max_length)

        def preprocess_function(examples):
            # Tokenize the texts
            args = (
                (examples[sentence1_key],) if sentence2_key is None else (examples[sentence1_key], examples[sentence2_key])
            )
            result = tokenizer(*args, padding=padding, max_length=max_seq_length, truncation=True)

            # Map labels to IDs (not necessary for GLUE tasks)
            if label_to_id is not None and "label" in examples:
                result["label"] = [(label_to_id[l] if l != -1 else -1) for l in examples["label"]]
            return result

        with training_args.main_process_first(desc="dataset map pre-processing"):
            self.raw_datasets = self.raw_datasets.map(
                preprocess_function,
                batched=True,
                load_from_cache_file=not data_args.overwrite_cache,
                desc="Running tokenizer on dataset",
            )

        if "validation" not in self.raw_datasets and "validation_matched" not in self.raw_datasets:
            raise ValueError("--do_eval requires a validation dataset")
        self.eval_dataset = self.raw_datasets["validation_matched" if self.task_name == "mnli" else "validation"]
        if data_args.max_eval_samples is not None:
            self.val_dataset = self.eval_dataset.select(range(data_args.max_eval_samples))

        # Get the metric function
        if self.task_name is not None:
            metric = load_metric("glue", self.task_name)
        else:
            metric = load_metric("accuracy")

        # You can define your custom compute_metrics function. It takes an `EvalPrediction` object (a namedtuple with a
        # predictions and label_ids field) and has to return a dictionary string to float.
        def compute_metrics(p: EvalPrediction):
            preds = p.predictions[0] if isinstance(p.predictions, tuple) else p.predictions
            preds = np.squeeze(preds) if self.is_regression else np.argmax(preds, axis=1)
            if self.task_name is not None:
                result = metric.compute(predictions=preds, references=p.label_ids)
                if len(result) > 1:
                    result["combined_score"] = np.mean(list(result.values())).item()
                return result
            elif self.is_regression:
                return {"mse": ((preds - p.label_ids) ** 2).mean().item()}
            else:
                return {"accuracy": (preds == p.label_ids).astype(np.float32).mean().item()}

        # Data collator will default to DataCollatorWithPadding, so we change it if we already did the padding.
        if data_args.pad_to_max_length:
            data_collator = default_data_collator
        elif training_args.fp16:
            data_collator = DataCollatorWithPadding(tokenizer, pad_to_multiple_of=8)
        else:
            data_collator = None

        # Initialize our Trainer
        eval_model = Trainer(
            model=model,
            args=training_args,
            train_dataset=None,
            eval_dataset=self.eval_dataset,
            compute_metrics=compute_metrics,
            tokenizer=tokenizer,
            data_collator=data_collator,
        )

        return eval_model

    def eval_bert(self, eval_eehead, eval_finalhead):

        passAcc = AverageMeter('passAcc@Avg', ':6.2f')
        moveonAcc = AverageMeter('mvonAcc@Avg', ':6.2f')
        moveonRatio = AverageMeter('mvonRatio@Avg', ':6.2f')
        avgAcc = AverageMeter('avgAcc@Avg', ':6.2f')

        tasks = [self.task_name]
        eval_datasets = [self.eval_dataset]
        if self.task_name == "mnli":
            tasks.append("mnli-mm")
            eval_datasets.append(self.raw_datasets["validation_mismatched"])

        self.moveon_dict = dict()
        self.hist_data = []
        if len(self.last_exit) == 1:
            last_moveon_dict = dict()
        else:
            with open('./moveon_dict/bert/{}/{}_exit_l{}_b{}_t{}.json'.format(self.task_name, self.task_name, self.last_exit, self.batch_size, self.metric_thres), 'rb') as f:
                last_moveon_dict = json.load(f)

        for i, (eval_dataset, task) in enumerate(zip(eval_datasets, tasks)):

            if len(self.last_exit) == 1:
                last_moveon_dict[str(i)] = [1]*len(eval_dataset)

            predictions = eval_eehead.predict(eval_dataset, metric_key_prefix="predict").predictions
            final_predictions = eval_finalhead.predict(eval_dataset, metric_key_prefix="predict").predictions

            pass_acc, moveon_acc, moveon_indicator = self.validate_bert(i, predictions, final_predictions,
                                 torch.tensor(last_moveon_dict[str(i)], dtype=torch.bool), eval_dataset)

            moveon_cnt = sum(moveon_indicator)
            last_moveon_cnt = sum(last_moveon_dict[str(i)])
            passAcc.update(pass_acc, last_moveon_cnt)
            moveonAcc.update(moveon_acc, last_moveon_cnt)
            moveonRatio.update(moveon_cnt/last_moveon_cnt, last_moveon_cnt)
            avgAcc.update(passAcc.val*(1-moveonRatio.val)+moveonAcc.val*moveonRatio.val, last_moveon_cnt)

        splited_moveon_indicator = [moveon_indicator[i:i+self.batch_size] for i in range(0,len(moveon_indicator), self.batch_size)]
        splited_last_moveon_dict = [last_moveon_dict['0'][i:i+self.batch_size] for i in range(0,len(last_moveon_dict['0']), self.batch_size)]
        for i in range(int(len(last_moveon_dict['0'])/self.batch_size) + 1):
            if sum(splited_last_moveon_dict[i]) != 0:
                splited_moveon_ratio = sum(splited_moveon_indicator[i])/sum(splited_last_moveon_dict[i])
                self.hist_data.append(splited_moveon_ratio.item())
            else:
                self.hist_data.append(0)

        # os.system("clear")
        print("passAcc: {}".format(passAcc.avg))
        print("moveonAcc: {}".format(moveonAcc.avg))
        print("moveon_ratio: {}".format(moveonRatio.avg))
        print("avgAcc: {}".format(avgAcc.avg))

        cnts = plt.hist(self.hist_data, bins=16, range=(0,1))
        print(cnts[0])

        with open('./moveon_dict/bert/{}/{}_exit_l{}_b{}_t{}.json'.format(self.task_name, self.task_name, self.exit_sequence, self.batch_size, self.metric_thres), "w+") as f:
                json.dump(self.moveon_dict, f)

        plt.close()

        return passAcc.avg.item(), moveonAcc.avg.item(), moveonRatio.avg.item(), avgAcc.avg.item()


    def validate_bert(self, idx, output, final_output, last_moveon_list, eval_dataset):

        output = torch.from_numpy(output)
        final_output = torch.from_numpy(final_output)
        target = torch.tensor(eval_dataset["label"])
        m = nn.Softmax(dim=1)
        softmax_output = m(output)
        softmax_final_output = m(final_output)

        pass_indicator = (torch.max(softmax_output, 1)[0] > self.p_thres) & last_moveon_list
        moveon_indicator = (torch.max(softmax_output, 1)[0] <= self.p_thres) & last_moveon_list
        self.moveon_dict[idx] = moveon_indicator.tolist()
        pass_cnt = sum(pass_indicator)
        moveon_cnt = sum(moveon_indicator)
        correct_indicator = (torch.max(softmax_output, 1)[1] == target) & last_moveon_list
        final_correct_indicator = (torch.max(softmax_final_output, 1)[1] == target) & last_moveon_list
        pass_correct_indicator = pass_indicator & correct_indicator
        moveon_correct_indicator = moveon_indicator & final_correct_indicator
        pass_correct_cnt = sum(pass_correct_indicator)
        moveon_correct_cnt = sum(moveon_correct_indicator)
        # print(str(int(pass_correct_cnt)) + '/' + str(int(pass_cnt)))
        if pass_cnt != 0:
            pass_acc = pass_correct_cnt.float().mul_(100.0 / pass_cnt)
        else:
            pass_acc = torch.tensor(0.0)

        if moveon_cnt != 0:
            moveon_acc = moveon_correct_cnt.float().mul_(100.0 / moveon_cnt)
        else:
            moveon_acc = torch.tensor(0.0)

        return pass_acc, moveon_acc, moveon_indicator

class convert_Wav2Vec2(object):

    def __init__(self, split_point) -> None:
        super().__init__()
        self.split_point = split_point
        self.p_thres = 0.8
        self.tokenizer = Wav2Vec2CTCTokenizer("./vocab.json", unk_token="[UNK]", pad_token="[PAD]", word_delimiter_token="|")
        self.feature_extractor = Wav2Vec2FeatureExtractor(feature_size=1, sampling_rate=16000, padding_value=0.0, do_normalize=True, return_attention_mask=False)
        self.processor = Wav2Vec2Processor(feature_extractor=self.feature_extractor, tokenizer=self.tokenizer)


    def remove_special_characters(self, batch):
        batch["text"] = re.sub(chars_to_ignore_regex, '', batch["text"]).lower()
        return batch

    def speech_file_to_array_fn(self, batch):
        speech_array, sampling_rate = sf.read(batch["file"])
        batch["speech"] = speech_array
        batch["sampling_rate"] = sampling_rate
        batch["target_text"] = batch["text"]
        return batch

    def prepare_dataset(self, batch):
        # check that all files have the correct sampling rate
        assert (
            len(set(batch["sampling_rate"])) == 1
        ), f"Make sure all inputs have the same sampling rate of {self.processor.feature_extractor.sampling_rate}."

        batch["input_values"] = self.processor(batch["speech"], sampling_rate=batch["sampling_rate"][0]).input_values
        
        with self.processor.as_target_processor():
            batch["labels"] = self.processor(batch["target_text"]).input_ids
        return batch

    @dataclass
    class DataCollatorCTCWithPadding:
        """
        Data collator that will dynamically pad the inputs received.
        Args:
            processor (:class:`~transformers.Wav2Vec2Processor`)
                The processor used for proccessing the data.
            padding (:obj:`bool`, :obj:`str` or :class:`~transformers.tokenization_utils_base.PaddingStrategy`, `optional`, defaults to :obj:`True`):
                Select a strategy to pad the returned sequences (according to the model's padding side and padding index)
                among:
                * :obj:`True` or :obj:`'longest'`: Pad to the longest sequence in the batch (or no padding if only a single
                sequence if provided).
                * :obj:`'max_length'`: Pad to a maximum length specified with the argument :obj:`max_length` or to the
                maximum acceptable input length for the model if that argument is not provided.
                * :obj:`False` or :obj:`'do_not_pad'` (default): No padding (i.e., can output a batch with sequences of
                different lengths).
            max_length (:obj:`int`, `optional`):
                Maximum length of the ``input_values`` of the returned list and optionally padding length (see above).
            max_length_labels (:obj:`int`, `optional`):
                Maximum length of the ``labels`` returned list and optionally padding length (see above).
            pad_to_multiple_of (:obj:`int`, `optional`):
                If set will pad the sequence to a multiple of the provided value.
                This is especially useful to enable the use of Tensor Cores on NVIDIA hardware with compute capability >=
                7.5 (Volta).
        """

        processor: Wav2Vec2Processor
        padding: Union[bool, str] = True
        max_length: Optional[int] = None
        max_length_labels: Optional[int] = None
        pad_to_multiple_of: Optional[int] = None
        pad_to_multiple_of_labels: Optional[int] = None

        def __call__(self, features: List[Dict[str, Union[List[int], torch.Tensor]]]) -> Dict[str, torch.Tensor]:
            # split inputs and labels since they have to be of different lenghts and need
            # different padding methods
            input_features = [{"input_values": feature["input_values"]} for feature in features]
            label_features = [{"input_ids": feature["labels"]} for feature in features]

            batch = self.processor.pad(
                input_features,
                padding=self.padding,
                max_length=self.max_length,
                pad_to_multiple_of=self.pad_to_multiple_of,
                return_tensors="pt",
            )
            with self.processor.as_target_processor():
                labels_batch = self.processor.pad(
                    label_features,
                    padding=self.padding,
                    max_length=self.max_length_labels,
                    pad_to_multiple_of=self.pad_to_multiple_of_labels,
                    return_tensors="pt",
                )

            # replace padding with -100 to ignore loss correctly
            labels = labels_batch["input_ids"].masked_fill(labels_batch.attention_mask.ne(1), -100)

            batch["labels"] = labels

            return batch

    def compute_metrics(self, pred):
        pred_logits = pred.predictions
        pred_ids = np.argmax(pred_logits, axis=-1)

        pred.label_ids[pred.label_ids == -100] = self.processor.tokenizer.pad_token_id

        pred_str = self.processor.batch_decode(pred_ids)
        # we do not want to group tokens when computing the metrics
        label_str = self.processor.batch_decode(pred.label_ids, group_tokens=False)

        wer_metric = load_metric("wer")
        wer = wer_metric.compute(predictions=pred_str, references=label_str)

        return {"wer": wer}


    def load_Wav2Vec2(self, split_point):
        net_wth_finalhead_dict = torch.load('/home/slzhang/projects/ETBA/Train/Wav2Vec2/checkpoints/timit_exit_12/checkpoint-435/pytorch_model.bin')
        net_wth_eehead_dict = torch.load('/home/slzhang/projects/ETBA/Train/Wav2Vec2/checkpoints/timit_exit_{}/checkpoint-435/pytorch_model.bin'.format(split_point))


        timit = load_dataset("timit_asr")
        timit = timit.remove_columns(["phonetic_detail", "word_detail", "dialect_region", "id", "sentence_type", "speaker_id"])
        timit = timit.map(self.remove_special_characters)
        timit = timit.map(self.speech_file_to_array_fn, remove_columns=timit.column_names["train"], num_proc=4)
        timit_prepared = timit.map(self.prepare_dataset, remove_columns=timit.column_names["train"], batch_size=8, num_proc=4, batched=True)

        data_collator = self.DataCollatorCTCWithPadding(processor=self.processor, padding=True)

        net_wth_finalhead = Wav2Vec2ForCTC.from_pretrained(
            "facebook/wav2vec2-base", 
            gradient_checkpointing=True, 
            ctc_loss_reduction="mean", 
            pad_token_id=self.processor.tokenizer.pad_token_id,
        )

        net_wth_eehead = Wav2Vec2_with_exit.from_pretrained(
            "facebook/wav2vec2-base", 
            gradient_checkpointing=True, 
            ctc_loss_reduction="mean", 
            pad_token_id=self.processor.tokenizer.pad_token_id,
        )
        net_wth_eehead.add_exit(self.split_point)

        dict_eehead = OrderedDict()
        dict_finalhead = OrderedDict()

        for k,v in net_wth_eehead.state_dict().items():
            dict_eehead[k] = net_wth_eehead_dict[k]
        net_wth_eehead.load_state_dict(dict_eehead)

        for k,v in net_wth_finalhead.state_dict().items():
            dict_finalhead[k] = net_wth_finalhead_dict[k]
        net_wth_finalhead.load_state_dict(dict_finalhead)

        eval_eehead = self.bert_aux(net_wth_eehead)
        eval_finalhead = self.bert_aux(net_wth_finalhead)

        return eval_eehead, eval_finalhead

    def eval_Wav2Vec2(self, eval_eehead, eval_finalhead):
        pass

        

# markdown format output
def _print_name_value(name_value, full_arch_name):
    names = name_value.keys()
    values = name_value.values()
    num_values = len(name_value)
    logger.info(
        '| Arch ' +
        ' '.join(['| {}'.format(name) for name in names]) +
        ' |'
    )
    logger.info('|---' * (num_values+1) + '|')
    logger.info(
        '| ' + full_arch_name + ' ' +
        ' '.join(['| {:.3f}'.format(value) for value in values]) +
         ' |'
    )


@dataclass
class DataTrainingArguments:
    """
    Arguments pertaining to what data we are going to input our model for training and eval.
    Using `HfArgumentParser` we can turn this class
    into argparse arguments to be able to specify them on
    the command line.
    """

    task_name: Optional[str] = field(
        default=None,
        metadata={"help": "The name of the task to train on: " + ", ".join(task_to_keys.keys())},
    )
    dataset_name: Optional[str] = field(
        default=None, metadata={"help": "The name of the dataset to use (via the datasets library)."}
    )
    dataset_config_name: Optional[str] = field(
        default=None, metadata={"help": "The configuration name of the dataset to use (via the datasets library)."}
    )
    max_seq_length: int = field(
        default=128,
        metadata={
            "help": "The maximum total input sequence length after tokenization. Sequences longer "
            "than this will be truncated, sequences shorter will be padded."
        },
    )
    overwrite_cache: bool = field(
        default=False, metadata={"help": "Overwrite the cached preprocessed datasets or not."}
    )
    pad_to_max_length: bool = field(
        default=True,
        metadata={
            "help": "Whether to pad all samples to `max_seq_length`. "
            "If False, will pad the samples dynamically when batching to the maximum length in the batch."
        },
    )
    max_train_samples: Optional[int] = field(
        default=None,
        metadata={
            "help": "For debugging purposes or quicker training, truncate the number of training examples to this "
            "value if set."
        },
    )
    max_eval_samples: Optional[int] = field(
        default=None,
        metadata={
            "help": "For debugging purposes or quicker training, truncate the number of evaluation examples to this "
            "value if set."
        },
    )
    max_predict_samples: Optional[int] = field(
        default=None,
        metadata={
            "help": "For debugging purposes or quicker training, truncate the number of prediction examples to this "
            "value if set."
        },
    )
    train_file: Optional[str] = field(
        default=None, metadata={"help": "A csv or a json file containing the training data."}
    )
    validation_file: Optional[str] = field(
        default=None, metadata={"help": "A csv or a json file containing the validation data."}
    )
    test_file: Optional[str] = field(default=None, metadata={"help": "A csv or a json file containing the test data."})

    def __post_init__(self):
        if self.task_name is not None:
            self.task_name = self.task_name.lower()
            if self.task_name not in task_to_keys.keys():
                raise ValueError("Unknown task, you should pick one in " + ",".join(task_to_keys.keys()))
        elif self.dataset_name is not None:
            pass
        elif self.train_file is None or self.validation_file is None:
            raise ValueError("Need either a GLUE task, a training/validation file or a dataset name.")
        else:
            train_extension = self.train_file.split(".")[-1]
            assert train_extension in ["csv", "json"], "`train_file` should be a csv or a json file."
            validation_extension = self.validation_file.split(".")[-1]
            assert (
                validation_extension == train_extension
            ), "`validation_file` should have the same extension (csv or json) as `train_file`."

@dataclass
class ModelArguments:
    """
    Arguments pertaining to which model/config/tokenizer we are going to fine-tune from.
    """
    split_point: int = field(
        metadata={"help": "Split point"}
    )
    model_name_or_path: str = field(
        metadata={"help": "Path to pretrained model or model identifier from huggingface.co/models"}
    )
    config_name: Optional[str] = field(
        default=None, metadata={"help": "Pretrained config name or path if not the same as model_name"}
    )
    tokenizer_name: Optional[str] = field(
        default=None, metadata={"help": "Pretrained tokenizer name or path if not the same as model_name"}
    )
    cache_dir: Optional[str] = field(
        default=None,
        metadata={"help": "Where do you want to store the pretrained models downloaded from huggingface.co"},
    )
    use_fast_tokenizer: bool = field(
        default=True,
        metadata={"help": "Whether to use one of the fast tokenizer (backed by the tokenizers library) or not."},
    )
    model_revision: str = field(
        default="main",
        metadata={"help": "The specific model version to use (can be a branch name, tag name or commit id)."},
    )
    use_auth_token: bool = field(
        default=False,
        metadata={
            "help": "Will use the token generated when running `transformers-cli login` (necessary to use this script "
            "with private models)."
        },
    )

class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self, name, fmt=':f'):
        self.name = name
        self.fmt = fmt
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count

    def __str__(self):
        fmtstr = '{name} {val' + self.fmt + '} ({avg' + self.fmt + '})'
        return fmtstr.format(**self.__dict__)

class ProgressMeter(object):
    def __init__(self, num_batches, meters, prefix=""):
        self.batch_fmtstr = self._get_batch_fmtstr(num_batches)
        self.meters = meters
        self.prefix = prefix

    def display(self, batch):
        entries = [self.prefix + self.batch_fmtstr.format(batch)]
        entries += [str(meter) for meter in self.meters]
        print('\t'.join(entries))

    def _get_batch_fmtstr(self, num_batches):
        num_digits = len(str(num_batches // 1))
        fmt = '{:' + str(num_digits) + 'd}'
        return '[' + fmt + '/' + fmt.format(num_batches) + ']'


def grid_search(task_name, split_point, batch_size, init=True, metric_thres=98, best_metric=1, last_exit=None, dataset='imagenet', all_or_sep=False):
    print('Grid searcing...')
    if task_name == 'resnet':

        if init == True:
            print('Grid searching for resnet...')
            inst = convert_resnet(split_point=split_point, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres, dataset_used=dataset, final_profile=all_or_sep)
            if all_or_sep == False:
                net_wth_eehead, net_wth_finalhead = inst.load_resnet()
            else:
                net_wth_eehead = inst.load_complete_resnet()
                net_wth_finalhead = None

            for p_thres in np.arange(0.05, 1.05, 0.05):
                inst.p_thres = p_thres
                metric_eehead, metric_finalhead, moveon_ratio, metric_avg = inst.eval_resnet(net_wth_eehead, net_wth_finalhead)
                wandb.log({'split_point':split_point, 'p_thres':p_thres, 'moveon_ratio':moveon_ratio, 'metric_avg':metric_avg})
                exit_sequence = last_exit+[split_point]
                print('p_thres: ' + str(p_thres) + '  moveon_ratio: ' + str(moveon_ratio) +'  metric_avg: ' + str(metric_avg))
                with open('/home/slzhang/projects/ETBA/Train/conversion_results/resnet_train{}_{}/resnet_results_{}_l{}.csv'.format('all' if all_or_sep else 'sep', dataset, dataset, exit_sequence), 'a+') as f:
                    writer = csv.writer(f)
                    writer.writerow([p_thres, metric_eehead, metric_finalhead, moveon_ratio, metric_avg])

        exit_sequence = last_exit+[split_point]
        print(exit_sequence)
        print('Grid searcing has been finished.')
        result = pd.read_csv('/home/slzhang/projects/ETBA/Train/conversion_results/resnet_train{}_{}/resnet_results_{}_l{}.csv'.format('all' if all_or_sep else 'sep', dataset, dataset, exit_sequence), header=None)
        if dataset == 'imagenet':
            result_satisfied = result[result.iloc[:,4]> best_metric*metric_thres*0.01]
        elif dataset == 'imagenette':
            result_satisfied = result[result.iloc[:,4]> best_metric*metric_thres*0.01]
        elif dataset == 'imagewoof':
            result_satisfied = result[result.iloc[:,4]> best_metric*metric_thres*0.01]
        opt_p_thres = result_satisfied[result_satisfied.iloc[:,3] == result_satisfied.iloc[:,3].min()].iloc[:,0]

        if len(opt_p_thres) > 1:
            return opt_p_thres.iloc[0]

        return opt_p_thres.item()

    elif task_name == 'posenet':
        if init == True:
            print('Grid searcing for posenet...')
            inst = convert_posenet(split_point=split_point, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres, final_profile=all_or_sep)
            for p_thres in np.arange(0.6, 1.0, 0.05):
                for n_thres in [5, 10, 15, 20, 30, 50]:
                    inst.p_thres = p_thres
                    inst.n_thres = n_thres
                    acc_pass, acc_moveon, moveon_ratio, metric_avg = inst.eval_posenet()
                    wandb.log({'split_point':split_point, 'p_thres':p_thres, 'n_thres': n_thres, 'moveon_ratio':moveon_ratio, 'metric_avg':metric_avg})
                    exit_sequence = last_exit+[split_point]
                    print('p_thres: ' + str(p_thres) + '  n_thres: ' + str(n_thres) + '  moveon_ratio: ' + str(moveon_ratio) +'  metric_avg: ' + str(metric_avg))
                    with open('/home/slzhang/projects/ETBA/Train/conversion_results/posenet_train{}/posenet_results_l{}.csv'.format('all' if all_or_sep else 'sep', exit_sequence), 'a+') as f:
                        writer = csv.writer(f)
                        writer.writerow([p_thres, n_thres, acc_pass, acc_moveon, moveon_ratio, metric_avg])
    
        exit_sequence = last_exit+[split_point]
        print(exit_sequence)
        print('Grid searcing has been finished.')
        result = pd.read_csv('/home/slzhang/projects/ETBA/Train/conversion_results/posenet_train{}/posenet_results_l{}.csv'.format('all' if all_or_sep else 'sep', exit_sequence), header=None)
        result_satisfied = result[result.iloc[:,5]> best_metric*metric_thres*0.01]
        opt_p_thres = result_satisfied[result_satisfied.iloc[:,4] == result_satisfied.iloc[:,4].min()].iloc[:,0]
        opt_n_thres = result_satisfied[result_satisfied.iloc[:,4] == result_satisfied.iloc[:,4].min()].iloc[:,1]
        print(opt_p_thres)

        if len(opt_p_thres) > 1:
            return opt_p_thres.iloc[0], opt_n_thres.iloc[0]

        return opt_p_thres.item(), opt_n_thres.item()

    elif task_name == 'openseg':
        if init == True:
            print('Grid searcing for openseg...')
            inst = convert_openseg(split_point=split_point, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres, final_profile=all_or_sep)
            for p_thres in np.arange(6, 10, 1):
                for n_thres in [500000, 700000, 900000, 1100000]:
                    inst.p_thres = p_thres
                    inst.n_thres = n_thres
                    metric_eehead, metric_finalhead, moveon_ratio, metric_avg = inst.eval_openseg()
                    wandb.log({'split_point':split_point, 'p_thres':p_thres, 'n_thres': n_thres, 'moveon_ratio':moveon_ratio, 'metric_avg':metric_avg})
                    exit_sequence = last_exit+[split_point]
                    print('p_thres: ' + str(p_thres) + '  n_thres: ' + str(n_thres) + '  moveon_ratio: ' + str(moveon_ratio) +'  metric_avg: ' + str(metric_avg))
                    with open('/home/slzhang/projects/ETBA/Train/conversion_results/openseg_train{}/openseg_results_l{}.csv'.format('all' if all_or_sep else 'sep', exit_sequence), 'a+') as f:
                        writer = csv.writer(f)
                        writer.writerow([p_thres, n_thres, metric_eehead, metric_finalhead, moveon_ratio, metric_avg])

        exit_sequence = last_exit+[split_point]
        print(exit_sequence)                
        print('Grid searcing has been finished.')
        result = pd.read_csv('/home/slzhang/projects/ETBA/Train/conversion_results/openseg_train{}/openseg_results_l{}.csv'.format('all' if all_or_sep else 'sep', exit_sequence), header=None)
        result_satisfied = result[result.iloc[:,5] > best_metric*metric_thres*0.01]
        opt_p_thres = result_satisfied[result_satisfied.iloc[:,4] == result_satisfied.iloc[:,4].min()].iloc[:,0]
        opt_n_thres = result_satisfied[result_satisfied.iloc[:,4] == result_satisfied.iloc[:,4].min()].iloc[:,1]
        print(opt_p_thres)

        if len(opt_p_thres) > 1:
            return opt_p_thres.iloc[0], opt_n_thres.iloc[0]

        return opt_p_thres.item(), opt_n_thres.item()

    elif task_name in ['cola', 'mnli', 'mrpc', 'qnli', 'qqp', 'rte', 'sst2', 'stsb', 'wnli']:
        if init == True:
            print('Grid searcing for {}...'.format(task_name))
            inst = convert_bert(split_point=split_point, task_name=task_name, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres)
            eval_eehead, eval_finalhead = inst.load_bert()
            for p_thres in np.arange(0.45, 1.05, 0.05):
                inst.p_thres = p_thres
                metric_eehead, metric_finalhead, moveon_ratio, metric_avg = inst.eval_bert(eval_eehead, eval_finalhead)
                wandb.log({'split_point':split_point, 'p_thres':p_thres, 'moveon_ratio':moveon_ratio, 'metric_avg':metric_avg})
                exit_sequence = last_exit+[split_point]
                with open('/home/slzhang/projects/ETBA/Train/conversion_results/bert_trainall/{}/{}_results_l{}.csv'.format(\
                        task_name, task_name, exit_sequence), 'a+') as f:
                    writer = csv.writer(f)
                    writer.writerow([p_thres, metric_eehead, metric_finalhead, moveon_ratio, metric_avg])
    
        exit_sequence = last_exit+[split_point]
        print(exit_sequence)
        print('Grid searcing has been finished.')
        result = pd.read_csv('/home/slzhang/projects/ETBA/Train/conversion_results/bert_trainall/{}/{}_results_l{}.csv'.format(\
                    task_name, task_name, exit_sequence), header=None)
        result_satisfied = result[result.iloc[:,4] > best_metric*metric_thres*0.01]
        opt_p_thres = result_satisfied[result_satisfied.iloc[:,3] == result_satisfied.iloc[:,3].min()].iloc[:,0]
        print(opt_p_thres)

        if len(opt_p_thres) > 1:
            return opt_p_thres.iloc[0]

        return opt_p_thres.item()

    elif task_name == 'Wav2Vec2':
        pass

if __name__ == '__main__':
    # inst = convert_resnet(split_point=22, batch_size=128, last_exit=9)
    # net_wth_eehead, net_wth_finalhead = inst.load_resnet()
    # inst.eval_resnet(net_wth_eehead, net_wth_finalhead)
    # exit()
    metric_list = {
    'imagenet':         77.34,
    'imagenet_new':     77.56,
    'imagewoof':        88.547,
    'imagenette':       90.29,
    'mrpc':             83.58,
    'sst2':             91.63,
    'rte':              64.98,
    'qnli':             90.83,
    'cola':             82.55,
    'posenet_ori':      0.8982,
    'posenet':          0.90017,
    'openseg':          0.7963, # 0.77058,
    }

    args = parse_args()

    task = args.task
    dataset_name = args.dataset_name
    mode = args.mode
    metric_thres = args.metric_thres
    init = args.init
    batch_size = args.batch_size
    last_exit = args.last_exit
    all_or_sep = args.all_or_sep
    
    exit_num = len(last_exit)
    all_or_sep_name = 'all' if all_or_sep else 'sep'

    task_metric = metric_list[dataset_name]
    if len(last_exit) == 1:
        best_metric = task_metric
    else:
        if task == 'resnet':
            result = pd.read_csv('/home/slzhang/projects/ETBA/Train/opt_thres_record/resnet_{}_train{}.csv'.format(\
                        dataset_name, all_or_sep_name), header=None)
        else:
            result = pd.read_csv('/home/slzhang/projects/ETBA/Train/opt_thres_record/{}_train{}.csv'.format(\
                        dataset_name, all_or_sep_name), header=None)
        best_metric = task_metric*metric_thres*0.01
        for i in range(1, len(last_exit)):
            if task in ['resnet', 'bert']:
                last_metric = result[result[0]==str(last_exit[:i+1])][result[1]==metric_thres][4].item()
                print(last_metric)
                mvon_ratio = result[result[0]==str(last_exit[:i+1])][result[1]==metric_thres][6].item()
                print(mvon_ratio)
                best_metric = (best_metric - last_metric*(1-mvon_ratio))/mvon_ratio
                print(best_metric)
            else:
                last_metric = result[result[0]==str(last_exit[:i+1])][result[1]==metric_thres][5].item()
                print(last_metric)
                mvon_ratio = result[result[0]==str(last_exit[:i+1])][result[1]==metric_thres][7].item()
                print(mvon_ratio)
                best_metric = (best_metric - last_metric*(1-mvon_ratio))/mvon_ratio
                print(best_metric)
        best_metric = best_metric/(0.01*metric_thres)

    if init:
        wandb.init(
            project="metric_convert", 
            name=task+'_'+dataset_name+'_'+all_or_sep_name+'_'+str(last_exit),
            config={
            "architecture": "resnet101",})

    if mode == 'test':
        if task == 'resnet':
            for split_point in range(last_exit[-1]+1, 33, 3):
                opt_p_thres = grid_search(task, split_point, batch_size, init=init, metric_thres=metric_thres, best_metric=best_metric, last_exit=last_exit, dataset=dataset_name, all_or_sep=all_or_sep)
                # p_thres_imagenet = {1:0.65, 4:0.65, 7:0.65, 10:0.6, 13:0.55, 16:0.5, 19:0.45, 22:0.3, 25:0.15, 28:0.05, 31:0.05}
                # p_thres_imagenette = {1:0.7, 4:0.7, 7:0.7, 10:0.7, 13:0.7, 16:0.6, 19:0.55, 22:0.5, 25:0.45, 28:0.3, 31:0.05}
                # p_thres_imagewoof = {1:0.7, 4:0.65, 7:0.65, 10:0.65, 13:0.6, 16:0.6, 19:0.55, 22:0.55, 25:0.55, 28:0.45, 31:0.05}
                # opt_p_thres = p_thres_imagenette[split_point]
                inst = convert_resnet(split_point=split_point, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres, dataset_used=dataset_name, final_profile=all_or_sep)
                inst.p_thres = opt_p_thres

                if all_or_sep == True: # train all exits together
                    net_wth_eehead = inst.load_complete_resnet()
                    a,b,c,d = inst.eval_resnet(net_wth_eehead, None)
                else:
                    net_wth_eehead, net_wth_finalhead = inst.load_resnet()
                    a,b,c,d = inst.eval_resnet(net_wth_eehead, net_wth_finalhead)

                with open('/home/slzhang/projects/ETBA/Train/opt_thres_record/resnet_{}_train{}.csv'.format(dataset_name, 'all' if all_or_sep else 'sep'), 'a+') as f:
                    writer = csv.writer(f)
                    writer.writerow([last_exit+[split_point], metric_thres, batch_size, opt_p_thres, a, b, c, d])

        elif task == 'posenet':
            for split_point in range(last_exit[-1]+1, 33, 3):
                opt_p_thres, opt_n_thres = grid_search(task, split_point, batch_size, init=init, metric_thres=metric_thres, last_exit=last_exit, best_metric=best_metric, all_or_sep=all_or_sep)
                inst = convert_posenet(split_point=split_point, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres, final_profile=all_or_sep)
                inst.p_thres = opt_p_thres
                inst.n_thres = opt_n_thres
                a,b,c,d = inst.eval_posenet()
                with open('/home/slzhang/projects/ETBA/Train/opt_thres_record/posenet_train{}.csv'.format('all' if all_or_sep else 'sep'), 'a+') as f:
                    writer = csv.writer(f)
                    writer.writerow([last_exit+[split_point], metric_thres, batch_size, opt_p_thres, opt_n_thres, a, b, c, d])

        elif task == 'openseg':
            for split_point in [10,13,16,19,22,25,28]:
                opt_p_thres, opt_n_thres = grid_search(task, split_point, batch_size, init=init, metric_thres=metric_thres, last_exit=last_exit, best_metric=best_metric, all_or_sep=all_or_sep)
                inst = convert_openseg(split_point=split_point, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres, final_profile=all_or_sep)
                inst.p_thres = opt_p_thres
                inst.n_thres = opt_n_thres
                a,b,c,d = inst.eval_openseg()
                with open('/home/slzhang/projects/ETBA/Train/opt_thres_record/openseg_train{}.csv'.format('all' if all_or_sep else 'sep'), 'a+') as f:
                    writer = csv.writer(f)
                    writer.writerow([last_exit+[split_point], metric_thres, batch_size, opt_p_thres, opt_n_thres, a, b, c, d])

        elif task == 'bert':
            for split_point in range(last_exit[-1]+1, 12):
                opt_p_thres = grid_search(dataset_name, split_point, batch_size, init=init, metric_thres=metric_thres, best_metric=best_metric, last_exit=last_exit)
                inst = convert_bert(split_point=split_point, task_name=dataset_name, batch_size=batch_size, last_exit=last_exit, metric_thres=metric_thres)
                inst.p_thres = opt_p_thres
                print(inst.p_thres)
                eval_eehead, eval_finalhead = inst.load_bert()
                a,b,c,d = inst.eval_bert(eval_eehead, eval_finalhead)
                with open('/home/slzhang/projects/ETBA/Train/opt_thres_record/{}_trainall.csv'.format(dataset_name), 'a+') as f:
                    writer = csv.writer(f)
                    writer.writerow([last_exit+[split_point], metric_thres, batch_size, opt_p_thres, a, b, c, d])

        elif task == 'Wav2Vec2':
            inst = convert_Wav2Vec2(split_point=5)
            inst.load_Wav2Vec2()
    # TODO: For bert, run "python metric_convert.py --output_dir /home/slzhang/projects/ETBA/Train/bert_train/models/tmp --split_point 5 --model_name_or_path bert-base-uncased --task_name mrpc --do_eval
    elif mode == 'final':
        if task == 'resnet':
            pass
        elif task == 'posenet':
            inst = convert_posenet(split_point=22, batch_size=32, last_exit=None, final_profile=True)
            acc_pass, acc_moveon, moveon_ratio, metric_avg = inst.eval_posenet()






# load_backbone()

# load state dict from the stage one model

# load_head()
