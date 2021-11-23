from typing import OrderedDict
import cv2
import os
import time
import logging
import numpy as np
import torch
import argparse
import torchvision.transforms as transforms
from tensorboardX import SummaryWriter
import torch.nn.parallel
import torch.backends.cudnn as cudnn

# resnet_s1 includes post_layers while partial_resnet does not
# resnet_s1 has dual-heads
import torchvision.models as models
from Mytrain.networks import resnet_s1, partial_resnet

# SpatialOCRNet_with_exit has dual-heads, while SpatialOCRNet_with_only_exit has only one exit
from openseg.lib.models.nets.ocrnet_with_exit import SpatialOCRNet_with_only_exit, SpatialOCRNet_with_exit
from openseg.lib.utils.tools.configer import Configer
from openseg.lib.datasets.data_loader import DataLoader
from openseg.lib.metrics import running_score as rslib
from openseg.segmentor.tools.data_helper import DataHelper
from openseg.segmentor.tools.evaluator import get_evaluator
from openseg.segmentor.etrainer import ETrainer
from openseg import main

# PoseResNetwthExit has dual-heads
from pose_estimation.lib.models.pose_resnet import PoseResNetwthExit, PoseResNetwthOnlyExit
from pose_estimation.lib.core.config import update_config, config, get_model_name
from pose_estimation.lib.core.function import validate_exit
from pose_estimation.lib.models import pose_resnet
from pose_estimation.lib.utils.utils import create_logger
from pose_estimation.lib.core.loss import DistillationBasedLoss
from pose_estimation.lib import dataset
from pose_estimation.lib.utils.transforms import flip_back
from pose_estimation.lib.core.evaluate import accuracy
from pose_estimation.lib.core.inference import get_final_preds
from pose_estimation.lib.utils.vis import save_debug_images

from bert_train.modeling_bert import BertWithExit, BertWithExit_s1, BertWithExit_s2

logger = logging.getLogger(__name__)

def load_resnet(split_point):
    net_wth_finalhead = models.resnet101(pretrained=True)
    net_wth_eehead = torch.load("/home/slzhang/projects/ETBA/Train/Mytrain/checkpoint.pth.tar."+str(split_point))

def eval_resnet(net):
    pass

def validate_resnet():
    pass

def load_posenet(split_point):
    net_wth_finalhead = torch.load("/home/slzhang/projects/ETBA/Train/pose_estimation/models/pytorch/pose_mpii/pose_resnet_101_384x384.pth.tar")
    net_wth_eehead = torch.load("/home/slzhang/projects/ETBA/Train/pose_estimation/output/mpii/pose_resnet_101/384x384_d256x3_adam_lr1e-3/checkpoint.pth.tar."+str(split_point))

    # for k,v in net_wth_eehead['state_dict'].items():
    #     print(k)

    cfg = "/home/slzhang/projects/ETBA/Train/pose_estimation/experiments/mpii/resnet101/384x384_d256x3_adam_lr1e-3.yaml"
    update_config(cfg)

    # cudnn related setting
    cudnn.benchmark = config.CUDNN.BENCHMARK
    torch.backends.cudnn.deterministic = config.CUDNN.DETERMINISTIC
    torch.backends.cudnn.enabled = config.CUDNN.ENABLED

    net_wth_dualheads = eval(config.MODEL.NAME+'.get_pose_net_with_exit')(
        config, is_train=True, start_point = split_point
    )

    dict_finalhead = net_wth_finalhead.copy()
    dict_finalhead_keys = list(net_wth_finalhead.keys())
    dict_eehead = net_wth_eehead['state_dict'].copy()
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

def eval_posenet(net):
    net = net.cuda()
    net.eval()

    logger, final_output_dir, tb_log_dir = create_logger(
    config, "/home/slzhang/projects/ETBA/Train/pose_estimation/experiments/mpii/resnet101/384x384_d256x3_adam_lr1e-3.yaml", 'train')

    gpus = [int(i) for i in config.GPUS.split(',')]
    net = torch.nn.DataParallel(net, device_ids=gpus).cuda()
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])
    valid_dataset = eval('dataset.'+config.DATASET.DATASET)(
        config,
        config.DATASET.ROOT,
        config.DATASET.TEST_SET,
        False,
        transforms.Compose([
            transforms.ToTensor(),
            normalize,
        ])
    )
    valid_loader = torch.utils.data.DataLoader(
        valid_dataset,
        batch_size=config.TEST.BATCH_SIZE*len(gpus),
        shuffle=False,
        num_workers=config.WORKERS,
        pin_memory=True
    )

    criterion = DistillationBasedLoss(C=0.5, maxprob = 0.5,
        use_target_weight=config.LOSS.USE_TARGET_WEIGHT
    ).cuda()

    perf_indicator = validate_posenet(0.7, 50, config, valid_loader, valid_dataset, net,
                                criterion, final_output_dir)

def validate_posenet(p_thres, n_thres, 
                    config, val_loader, val_dataset, model, criterion, output_dir, writer_dict=None):
    batch_time = AverageMeter('batch_time', ':6.2f')
    losses = AverageMeter('losses', ':6.2f')
    acc = AverageMeter('acc', ':6.2f')
    moveon_ratio = AverageMeter('Ratio@Pass', ':6.2f')

    # switch to evaluate mode
    model.eval()

    num_samples = len(val_dataset)
    all_preds = np.zeros((num_samples, config.MODEL.NUM_JOINTS, 3),
                         dtype=np.float32)
    all_boxes = np.zeros((num_samples, 6))
    image_path = []
    filenames = []
    imgnums = []
    idx = 0
    with torch.no_grad():
        end = time.time()
        for i, (input, target, target_weight, meta) in enumerate(val_loader):
            # compute output
            output, exit_output = model(input)
            if config.TEST.FLIP_TEST:
                # this part is ugly, because pytorch has not supported negative index
                # input_flipped = model(input[:, :, :, ::-1])
                input_flipped = np.flip(input.cpu().numpy(), 3).copy()
                input_flipped = torch.from_numpy(input_flipped).cuda()
                output_flipped, exit_output_flipped = model(input_flipped)
                output_flipped = flip_back(output_flipped.cpu().numpy(),
                                           val_dataset.flip_pairs)
                output_flipped = torch.from_numpy(output_flipped.copy()).cuda()
                exit_output_flipped = flip_back(exit_output_flipped.cpu().numpy(),
                                           val_dataset.flip_pairs)
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

            pixel_confidence = p_thres
            num_threshold = n_thres
            for j in range(output.shape[0]):
                if len(exit_output[j][exit_output[j] > pixel_confidence]) > num_threshold:
                    moveon_ratio.update(0, 1)
                else:
                    moveon_ratio.update(1, 1)
                    exit_output[j] = output[j]
            # print(move_on_cnt)
            # print('exit_output' + str(len(exit_output[exit_output > 0.8])))
            # print('output' + str(len(output[i][output[i] > 0.8])))

            target = target.cuda(non_blocking=True)
            target_weight = target_weight.cuda(non_blocking=True)

            loss = criterion(output, exit_output, target, target_weight)

            num_images = input.size(0)
            # measure accuracy and record loss
            losses.update(loss.item(), num_images)
            _, avg_acc, cnt, pred = accuracy(exit_output.cpu().numpy(),
                                             target.cpu().numpy())

            # prefix = '{}_{}'.format(os.path.join(output_dir, 'test'), 0)
            # save_debug_images_with_exit(config, input, meta, target, pred*4, 
            #                             output, exit_output, prefix)
            # exit()

            acc.update(avg_acc, cnt)

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

            if i % config.PRINT_FREQ == 0:
                # wandb.log({"acc":acc, "loss":loss})
                msg = 'Test: [{0}/{1}]\t' \
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t' \
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t' \
                      'Accuracy {acc.val:.3f} ({acc.avg:.3f})\t' \
                      'Moveon_Ratio {moveon_ratio.val:.3f} ({moveon_ratio.avg:.3f})'.format(
                          i, len(val_loader), batch_time=batch_time,
                          loss=losses, acc=acc, moveon_ratio=moveon_ratio)
                logger.info(msg)

                # prefix = '{}_{}'.format(os.path.join(output_dir, 'val'), i)
                # save_debug_images(config, input, meta, target, pred*4, exit_output,
                #                   prefix)

        name_values, perf_indicator = val_dataset.evaluate(
            config, all_preds, output_dir, all_boxes, image_path,
            filenames, imgnums)

        _, full_arch_name = get_model_name(config)
        if isinstance(name_values, list):
            for name_value in name_values:
                _print_name_value(name_value, full_arch_name)
        else:
            _print_name_value(name_values, full_arch_name)

    return perf_indicator


def load_openseg(split_point):
    # load the backbone of the network with dual-heads

    net_wth_finalhead = torch.load("/home/slzhang/projects/ETBA/Train/openseg/checkpoints/cityscapes/ocrnet_resnet101_s33_latest.pth")
    # for k,v in net_wth_finalhead['state_dict'].items():
    #     print(k)

    config = Configer(configs="/home/slzhang/projects/ETBA/Train/openseg/configs/cityscapes/R_101_D_8_with_exit.json")
    config.update(["network", "split_point"], split_point)
    net_wth_eehead = torch.load("/home/slzhang/projects/ETBA/Train/openseg/checkpoints/cityscapes/ocrnet_resnet101_s"+str(split_point)+"_latest.pth")
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

def eval_openseg(net):
    net = net.cuda()
    net.eval()
    config = Configer(configs="/home/slzhang/projects/ETBA/Train/openseg/configs/cityscapes/R_101_D_8_with_exit.json")
    abs_data_dir = "/home/slzhang/projects/ETBA/Train/openseg/data/cityscapes"
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

    moveon_ratio = AverageMeter('Ratio@Pass', ':6.2f')
    mIoU = AverageMeter('mIoU@Avg', ':6.2f')
    mIoU_s1 = AverageMeter('mIoU_s1@Avg', ':6.2f')
    mIoU_s2 = AverageMeter('mIoU_s2@Avg', ':6.2f')

    for j, data_dict in enumerate(val_loader):
        (inputs, targets), batch_size = data_helper.prepare_data(data_dict)
        with torch.no_grad():
            outputs = net(*inputs)
            if isinstance(outputs, torch.Tensor):
                outputs = [outputs]
            metas = data_dict["meta"]
            output_s1 = outputs[1].permute(0, 2, 3, 1)[0].cpu().numpy()
            output_s2 = outputs[3].permute(0, 2, 3, 1)[0].cpu().numpy()
            final_output = validate_openseg(output_s1, output_s2, moveon_ratio)

            labelmap = np.argmax(final_output, axis=-1)
            ori_target = metas[0]['ori_target']
            RunningScore = rslib.RunningScore(config)
            RunningScore.update(labelmap[None], ori_target[None])
            rs = RunningScore.get_mean_iou()
            if moveon_ratio.val == 0:
                mIoU_s1.update(rs)
            else:
                mIoU_s2.update(rs)
            mIoU.update(rs)
            os.system("clear")
            print("mIoU: {}".format(mIoU.avg))
            print("mIoU_s1: {}".format(mIoU_s1.avg))
            print("mIoU_s2: {}".format(mIoU_s2.avg))
            print("moveon_ratio: {}".format(moveon_ratio.avg))

def validate_openseg(p_thres, n_thres, 
                    output_s1, output_s2, moveon_ratio):
    # Shape of output_s1/output_s2: (1024, 2048, 19)
    pixel_threshold = 8
    num_threshold = 0
    pixel_confidence = np.amax(output_s1, axis=-1)
    # print(pixel_confidence)
    pixel_over_threshold = pixel_confidence > pixel_threshold
    num_pixel_over_threshold = pixel_over_threshold.sum()
    # print(num_pixel_over_threshold)
    if num_pixel_over_threshold > num_threshold:
        moveon_ratio.update(0, 1)
        return output_s1
    else:
        moveon_ratio.update(1, 1)
        return output_s2

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

if __name__ == '__main__':
    # net = load_openseg()
    # eval_openseg(net)
    net = load_posenet(20)
    eval_posenet(net)


# load_backbone()

# load state dict from the stage one model

# load_head()
