# ------------------------------------------------------------------------------
# Copyright (c) Microsoft
# Licensed under the MIT License.
# Written by Bin Xiao (Bin.Xiao@microsoft.com)
# ------------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import logging

import copy
import torch
import torch.nn as nn
from collections import OrderedDict

import sys
sys.path.append("/home/slzhang/projects/ETBA/Inference/src/exit_placement")
from networks import backbone_s1, backbone_s2, Bottleneck

BN_MOMENTUM = 0.1
logger = logging.getLogger(__name__)


def conv3x3(in_planes, out_planes, stride=1):
    """3x3 convolution with padding"""
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                     padding=1, bias=False)


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(BasicBlock, self).__init__()
        self.conv1 = conv3x3(inplanes, planes, stride)
        self.bn1 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(planes, planes)
        self.bn2 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


# class Bottleneck(nn.Module):
#     expansion = 4

#     def __init__(self, inplanes, planes, stride=1, downsample=None):
#         super(Bottleneck, self).__init__()
#         self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, bias=False)
#         self.bn1 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
#         self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride,
#                                padding=1, bias=False)
#         self.bn2 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
#         self.conv3 = nn.Conv2d(planes, planes * self.expansion, kernel_size=1,
#                                bias=False)
#         self.bn3 = nn.BatchNorm2d(planes * self.expansion,
#                                   momentum=BN_MOMENTUM)
#         self.relu = nn.ReLU(inplace=True)
#         self.downsample = downsample
#         self.stride = stride

#     def forward(self, x):
#         residual = x

#         out = self.conv1(x)
#         out = self.bn1(out)
#         out = self.relu(out)

#         out = self.conv2(out)
#         out = self.bn2(out)
#         out = self.relu(out)

#         out = self.conv3(out)
#         out = self.bn3(out)

#         if self.downsample is not None:
#             residual = self.downsample(x)

#         out += residual
#         out = self.relu(out)

#         return out


class Bottleneck_CAFFE(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(Bottleneck_CAFFE, self).__init__()
        # add stride to conv1x1
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, stride=stride, bias=False)
        self.bn1 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=1,
                               padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.conv3 = nn.Conv2d(planes, planes * self.expansion, kernel_size=1,
                               bias=False)
        self.bn3 = nn.BatchNorm2d(planes * self.expansion,
                                  momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class PoseResNet(nn.Module):

    def __init__(self, block, layers, cfg, **kwargs):
        self.inplanes = 64
        extra = cfg.MODEL.EXTRA
        self.deconv_with_bias = extra.DECONV_WITH_BIAS

        super(PoseResNet, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3,
                               bias=False)
        self.bn1 = nn.BatchNorm2d(64, momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=2)

        # used for deconv layers
        self.deconv_layers = self._make_deconv_layer(
            extra.NUM_DECONV_LAYERS,
            extra.NUM_DECONV_FILTERS,
            extra.NUM_DECONV_KERNELS,
        )

        self.final_layer = nn.Conv2d(
            in_channels=extra.NUM_DECONV_FILTERS[-1],
            out_channels=cfg.MODEL.NUM_JOINTS,
            kernel_size=extra.FINAL_CONV_KERNEL,
            stride=1,
            padding=1 if extra.FINAL_CONV_KERNEL == 3 else 0
        )

    def _make_layer(self, block, planes, blocks, stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion, momentum=BN_MOMENTUM),
            )

        layers = []
        layers.append(block(self.inplanes, planes, stride, downsample))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes))

        return nn.Sequential(*layers)

    def _get_deconv_cfg(self, deconv_kernel, index):
        if deconv_kernel == 4:
            padding = 1
            output_padding = 0
        elif deconv_kernel == 3:
            padding = 1
            output_padding = 1
        elif deconv_kernel == 2:
            padding = 0
            output_padding = 0

        return deconv_kernel, padding, output_padding

    def _make_deconv_layer(self, num_layers, num_filters, num_kernels):
        assert num_layers == len(num_filters), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'
        assert num_layers == len(num_kernels), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'

        layers = []
        for i in range(num_layers):
            kernel, padding, output_padding = \
                self._get_deconv_cfg(num_kernels[i], i)

            planes = num_filters[i]
            layers.append(
                nn.ConvTranspose2d(
                    in_channels=self.inplanes,
                    out_channels=planes,
                    kernel_size=kernel,
                    stride=2,
                    padding=padding,
                    output_padding=output_padding,
                    bias=self.deconv_with_bias))
            layers.append(nn.BatchNorm2d(planes, momentum=BN_MOMENTUM))
            layers.append(nn.ReLU(inplace=True))
            self.inplanes = planes

        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        x = self.deconv_layers(x)
        x = self.final_layer(x)

        return x

    def init_weights(self, pretrained=''):
        if os.path.isfile(pretrained):
            logger.info('=> init deconv weights from normal distribution')
            for name, m in self.deconv_layers.named_modules():
                if isinstance(m, nn.ConvTranspose2d):
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    if self.deconv_with_bias:
                        nn.init.constant_(m.bias, 0)
                elif isinstance(m, nn.BatchNorm2d):
                    logger.info('=> init {}.weight as 1'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.constant_(m.weight, 1)
                    nn.init.constant_(m.bias, 0)
            logger.info('=> init final conv weights from normal distribution')
            for m in self.final_layer.modules():
                if isinstance(m, nn.Conv2d):
                    # nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    nn.init.constant_(m.bias, 0)

            # pretrained_state_dict = torch.load(pretrained)
            logger.info('=> loading pretrained model {}'.format(pretrained))
            # self.load_state_dict(pretrained_state_dict, strict=False)
            checkpoint = torch.load(pretrained)
            if isinstance(checkpoint, OrderedDict):
                state_dict = checkpoint
            elif isinstance(checkpoint, dict) and 'state_dict' in checkpoint:
                state_dict_old = checkpoint['state_dict']
                state_dict = OrderedDict()
                # delete 'module.' because it is saved from DataParallel module
                for key in state_dict_old.keys():
                    if key.startswith('module.'):
                        # state_dict[key[7:]] = state_dict[key]
                        # state_dict.pop(key)
                        state_dict[key[7:]] = state_dict_old[key]
                    else:
                        state_dict[key] = state_dict_old[key]
            else:
                raise RuntimeError(
                    'No state_dict found in checkpoint file {}'.format(pretrained))
            self.load_state_dict(state_dict, strict=False)
        else:
            logger.error('=> imagenet pretrained model dose not exist')
            logger.error('=> please download it first')
            raise ValueError('imagenet pretrained model does not exist')

class PoseResNetwthExit(nn.Module):
    def __init__(self, block, layers, cfg, start_point, **kwargs):
        super(PoseResNetwthExit, self).__init__()
        extra = cfg.MODEL.EXTRA
        self.deconv_with_bias = extra.DECONV_WITH_BIAS
        self.backbone_s1 = backbone_s1(start_point=start_point, end_point=33)
        # self.backbone_s2 = backbone_s2(start_point=start_point, end_point=start_point)

        self.inplanes = 2048
        self.deconv_layers = self._make_deconv_layer(
            extra.NUM_DECONV_LAYERS,
            extra.NUM_DECONV_FILTERS,
            extra.NUM_DECONV_KERNELS,
        )

        self.final_layer = nn.Conv2d(
            in_channels=extra.NUM_DECONV_FILTERS[-1],
            out_channels=cfg.MODEL.NUM_JOINTS,
            kernel_size=extra.FINAL_CONV_KERNEL,
            stride=1,
            padding=1 if extra.FINAL_CONV_KERNEL == 3 else 0
        )

        self.inplanes = 2048
        self.head_deconv_layers = self._make_deconv_layer(
            extra.NUM_DECONV_LAYERS,
            extra.NUM_DECONV_FILTERS,
            extra.NUM_DECONV_KERNELS,
        )

        self.head_final_layer = nn.Conv2d(
            in_channels=extra.NUM_DECONV_FILTERS[-1],
            out_channels=cfg.MODEL.NUM_JOINTS,
            kernel_size=extra.FINAL_CONV_KERNEL,
            stride=1,
            padding=1 if extra.FINAL_CONV_KERNEL == 3 else 0
        )

    def _get_deconv_cfg(self, deconv_kernel, index):
        if deconv_kernel == 4:
            padding = 1
            output_padding = 0
        elif deconv_kernel == 3:
            padding = 1
            output_padding = 1
        elif deconv_kernel == 2:
            padding = 0
            output_padding = 0

        return deconv_kernel, padding, output_padding

    def _make_deconv_layer(self, num_layers, num_filters, num_kernels):
        assert num_layers == len(num_filters), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'
        assert num_layers == len(num_kernels), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'

        layers = []
        for i in range(num_layers):
            kernel, padding, output_padding = \
                self._get_deconv_cfg(num_kernels[i], i)

            planes = num_filters[i]
            layers.append(
                nn.ConvTranspose2d(
                    in_channels=self.inplanes,
                    out_channels=planes,
                    kernel_size=kernel,
                    stride=2,
                    padding=padding,
                    output_padding=output_padding,
                    bias=self.deconv_with_bias))
            layers.append(nn.BatchNorm2d(planes, momentum=BN_MOMENTUM))
            layers.append(nn.ReLU(inplace=True))
            self.inplanes = planes

        return nn.Sequential(*layers)

    def forward(self, input):
        x, x_exit = self.backbone_s1(input)
        x_exit = self.head_deconv_layers(x_exit)
        x_exit = self.head_final_layer(x_exit)

        # x = self.backbone_s2(x)

        x = self.deconv_layers(x)
        x = self.final_layer(x)

        return x, x_exit

    def init_weights(self, pretrained=''):
        if os.path.isfile(pretrained):
            logger.info('=> init head deconv weights from normal distribution')

            # for name, m in self.named_parameters():
            #     m.requires_grad = False

            for name, m in self.head_deconv_layers.named_modules():
                if isinstance(m, nn.ConvTranspose2d):
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    if self.deconv_with_bias:
                        nn.init.constant_(m.bias, 0)
                elif isinstance(m, nn.BatchNorm2d):
                    logger.info('=> init {}.weight as 1'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.constant_(m.weight, 1)
                    nn.init.constant_(m.bias, 0)
            logger.info('=> init head final conv weights from normal distribution')
            for m in self.head_final_layer.modules():
                if isinstance(m, nn.Conv2d):
                    # nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    nn.init.constant_(m.bias, 0)

            # for name, m in self.head_deconv_layers.named_parameters():
            #     m.requires_grad = True
            # for name, m in self.head_final_layer.named_parameters():
            #     m.requires_grad = True

            # pretrained_state_dict = torch.load(pretrained)
            logger.info('=> loading pretrained model {}'.format(pretrained))
            # self.load_state_dict(pretrained_state_dict, strict=False)
            checkpoint = torch.load(pretrained)
            if isinstance(checkpoint, OrderedDict):
                state_dict = checkpoint
            elif isinstance(checkpoint, dict) and 'state_dict' in checkpoint:
                state_dict_old = checkpoint['state_dict']
                state_dict = OrderedDict()
                # delete 'module.' because it is saved from DataParallel module

                for key in state_dict_old.keys():
                    if key.startswith('module.'):
                        # state_dict[key[7:]] = state_dict[key]
                        # state_dict.pop(key)
                        state_dict[key[7:]] = state_dict_old[key]
                    else:
                        state_dict[key] = state_dict_old[key]
            else:
                raise RuntimeError(
                    'No state_dict found in checkpoint file {}'.format(pretrained))
            self.load_state_dict(state_dict, strict=False)
        else:
            logger.error('=> imagenet pretrained model dose not exist')
            logger.error('=> please download it first')
            raise ValueError('imagenet pretrained model does not exist')

class PoseResNetwthOnlyExit(nn.Module):
    def __init__(self, block, layers, cfg, start_point, **kwargs):
        super(PoseResNetwthOnlyExit, self).__init__()
        extra = cfg.MODEL.EXTRA
        self.deconv_with_bias = extra.DECONV_WITH_BIAS
        self.backbone_s1 = backbone_s1(start_point=start_point, end_point=start_point)
        # self.backbone_s2 = backbone_s2(start_point=start_point, end_point=start_point)

        self.inplanes = 2048
        self.deconv_layers = self._make_deconv_layer(
            extra.NUM_DECONV_LAYERS,
            extra.NUM_DECONV_FILTERS,
            extra.NUM_DECONV_KERNELS,
        )

        self.final_layer = nn.Conv2d(
            in_channels=extra.NUM_DECONV_FILTERS[-1],
            out_channels=cfg.MODEL.NUM_JOINTS,
            kernel_size=extra.FINAL_CONV_KERNEL,
            stride=1,
            padding=1 if extra.FINAL_CONV_KERNEL == 3 else 0
        )

    def _get_deconv_cfg(self, deconv_kernel, index):
        if deconv_kernel == 4:
            padding = 1
            output_padding = 0
        elif deconv_kernel == 3:
            padding = 1
            output_padding = 1
        elif deconv_kernel == 2:
            padding = 0
            output_padding = 0

        return deconv_kernel, padding, output_padding

    def _make_deconv_layer(self, num_layers, num_filters, num_kernels):
        assert num_layers == len(num_filters), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'
        assert num_layers == len(num_kernels), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'

        layers = []
        for i in range(num_layers):
            kernel, padding, output_padding = \
                self._get_deconv_cfg(num_kernels[i], i)

            planes = num_filters[i]
            layers.append(
                nn.ConvTranspose2d(
                    in_channels=self.inplanes,
                    out_channels=planes,
                    kernel_size=kernel,
                    stride=2,
                    padding=padding,
                    output_padding=output_padding,
                    bias=self.deconv_with_bias))
            layers.append(nn.BatchNorm2d(planes, momentum=BN_MOMENTUM))
            layers.append(nn.ReLU(inplace=True))
            self.inplanes = planes

        return nn.Sequential(*layers)

    def forward(self, input):
        x, x_exit = self.backbone_s1(input)
        x_exit = self.deconv_layers(x_exit)
        x_exit = self.final_layer(x_exit)

        return x_exit

    def init_weights(self, pretrained=''):
        # for k,v in self.state_dict().items():
        #     print(k)
        if os.path.isfile(pretrained):
            logger.info('=> init head deconv weights from normal distribution')

            # for name, m in self.named_parameters():
            #     m.requires_grad = False

            for name, m in self.deconv_layers.named_modules():
                if isinstance(m, nn.ConvTranspose2d):
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    if self.deconv_with_bias:
                        nn.init.constant_(m.bias, 0)
                elif isinstance(m, nn.BatchNorm2d):
                    logger.info('=> init {}.weight as 1'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.constant_(m.weight, 1)
                    nn.init.constant_(m.bias, 0)
            logger.info('=> init head final conv weights from normal distribution')
            for m in self.final_layer.modules():
                if isinstance(m, nn.Conv2d):
                    # nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    nn.init.constant_(m.bias, 0)

            # for name, m in self.head_deconv_layers.named_parameters():
            #     m.requires_grad = True
            # for name, m in self.head_final_layer.named_parameters():
            #     m.requires_grad = True

            # pretrained_state_dict = torch.load(pretrained)
            logger.info('=> loading pretrained model {}'.format(pretrained))
            # self.load_state_dict(pretrained_state_dict, strict=False)
            checkpoint = torch.load(pretrained)
            dict_trained = checkpoint.copy()
            dict_new = OrderedDict()

            for k,v in self.state_dict().items():
                if 'num_batches_tracked' not in k:
                    if 'backbone_s1.pre' in k:
                        dict_new[k] = dict_trained[k[16:]]
                    elif 'backbone_s1.exit' in k:
                        if len(self.backbone_s1.exit) == 1:
                            dict_new[k] = dict_trained['layer4.0.'+k[19:]]
                        elif len(self.backbone_s1.exit) == 2:
                            if 'exit.0' in k:
                                dict_new[k] = dict_trained['layer3.0.'+k[19:]]
                            elif 'exit.1' in k:
                                dict_new[k] = dict_trained['layer4.0.'+k[19:]]
                        elif len(self.backbone_s1.exit) == 3:
                            if 'exit.0' in k:
                                dict_new[k] = dict_trained['layer2.0.'+k[19:]]
                            elif 'exit.1' in k:
                                dict_new[k] = dict_trained['layer3.0.'+k[19:]]
                            elif 'exit.2' in k:
                                dict_new[k] = dict_trained['layer4.0.'+k[19:]]
                    elif 'deconv' in k or 'final' in k:
                        dict_new[k] = dict_trained[k]
                    else:
                        dict_new[k] = dict_trained[k[12:]]

            # for k,v in dict_new.items():
            #     print(k)
            # if isinstance(checkpoint, OrderedDict):
            #     state_dict = checkpoint
            # elif isinstance(checkpoint, dict) and 'state_dict' in checkpoint:
            #     state_dict_old = checkpoint['state_dict']
            #     state_dict = OrderedDict()
            #     # delete 'module.' because it is saved from DataParallel module

            #     for key in state_dict_old.keys():
            #         if key.startswith('module.'):
            #             # state_dict[key[7:]] = state_dict[key]
            #             # state_dict.pop(key)
            #             state_dict[key[7:]] = state_dict_old[key]
            #         else:
            #             state_dict[key] = state_dict_old[key]
            # else:
            #     raise RuntimeError(
            #         'No state_dict found in checkpoint file {}'.format(pretrained))

            # freeze the backbone parameters
            for k,v in self.named_parameters():
                if 'backbone' in k and 'exit' not in k:
                    v.requires_grad=False
                else:
                    v.requires_grad=True

            self.load_state_dict(dict_new, strict=False)

        else:
            logger.error('=> imagenet pretrained model dose not exist')
            logger.error('=> please download it first')
            raise ValueError('imagenet pretrained model does not exist')

class PoseResNetwthMultiExit(nn.Module):
    def __init__(self, block, layers, cfg, exit_list, **kwargs):
        super(PoseResNetwthMultiExit, self).__init__()
        extra = cfg.MODEL.EXTRA
        self.deconv_with_bias = extra.DECONV_WITH_BIAS
        self.ori_backbone = nn.ModuleList()
        self.backbone = nn.ModuleList()
        self.exit_list = exit_list
        for i in range(len(exit_list)-1):
            self.ori_backbone.append(get_pose_net_with_only_exit(cfg, is_train=True, start_point = self.exit_list[i]))
            # state_dict = torch.load('/home/slzhang/projects/ETBA/Train/pose_estimation/checkpoints/split_point_{}/model_best.pth'.format(self.exit_list[i]))
            # new_dict = OrderedDict()

            # for k,v in self.ori_backbone[i].state_dict().items():
            #     new_dict[k] = state_dict['module.'+k]
            # self.ori_backbone[i].load_state_dict(new_dict, strict=True)

        self.ori_backbone.append(get_pose_net_with_only_exit(cfg, is_train=True, start_point = 33))
        net_wth_finalhead = torch.load('/home/slzhang/projects/ETBA/Train/pose_estimation/checkpoints/pose_resnet_101_384x384.pth.tar')
        
        new_dict = OrderedDict()
        dict_finalhead = net_wth_finalhead.copy()
        dict_finalhead_keys = list(net_wth_finalhead.keys())
        i = 0
        for k,v in self.ori_backbone[len(exit_list)-1].state_dict().items():
            if 'num_batches_tracked' not in k:
                new_dict[k] = dict_finalhead[dict_finalhead_keys[i]]
                i = i + 1
        self.ori_backbone[len(exit_list)-1].load_state_dict(new_dict, strict=True)

        ori_backbone_copy = copy.deepcopy(self.ori_backbone)

        for i in range(len(exit_list)):
            if i == 0:
                flatt_model = nn.Sequential(*list(ori_backbone_copy[i].backbone_s1.children())[:-1])
                self.backbone.append(flatt_model)
            else:
                print('-------------------')
                backbone = nn.Sequential()
                last_bottleneck_num = 0
                for layer in ori_backbone_copy[i-1].backbone_s1.named_modules():
                    if isinstance(layer[1], Bottleneck) and 'exit' not in layer[0]:
                        last_bottleneck_num = last_bottleneck_num + 1

                cnt = 0
                for layer in ori_backbone_copy[i].backbone_s1.named_modules():
                    if isinstance(layer[1], Bottleneck) and 'exit' not in layer[0]:
                        cnt = cnt + 1
                        if cnt > last_bottleneck_num:
                            backbone.add_module(layer[0].replace('.',' '), layer[1])

                self.backbone.append(backbone)
            for k,v in self.backbone[i].named_parameters():
                v.requires_grad=True
            for k,v in self.ori_backbone[i].named_parameters():
                v.requires_grad=True

        self.exit = nn.ModuleList()
        self.deconv_layers = nn.ModuleList()
        self.final_layer = nn.ModuleList()

        for i in range(len(exit_list)):
            self.exit.append(self.ori_backbone[i].backbone_s1.exit)
            self.deconv_layers.append(self.ori_backbone[i].deconv_layers)
            self.final_layer.append(self.ori_backbone[i].final_layer)
        
        print(self.exit_list)
        del(self.ori_backbone)


    def _get_deconv_cfg(self, deconv_kernel, index):
        if deconv_kernel == 4:
            padding = 1
            output_padding = 0
        elif deconv_kernel == 3:
            padding = 1
            output_padding = 1
        elif deconv_kernel == 2:
            padding = 0
            output_padding = 0

        return deconv_kernel, padding, output_padding

    def _make_deconv_layer(self, num_layers, num_filters, num_kernels):
        assert num_layers == len(num_filters), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'
        assert num_layers == len(num_kernels), \
            'ERROR: num_deconv_layers is different len(num_deconv_filters)'

        layers = []
        for i in range(num_layers):
            kernel, padding, output_padding = \
                self._get_deconv_cfg(num_kernels[i], i)

            planes = num_filters[i]
            layers.append(
                nn.ConvTranspose2d(
                    in_channels=self.inplanes,
                    out_channels=planes,
                    kernel_size=kernel,
                    stride=2,
                    padding=padding,
                    output_padding=output_padding,
                    bias=self.deconv_with_bias))
            layers.append(nn.BatchNorm2d(planes, momentum=BN_MOMENTUM))
            layers.append(nn.ReLU(inplace=True))
            self.inplanes = planes

        return nn.Sequential(*layers)

    def forward(self, x):
        output = []
        for i in range(len(self.exit_list)):
            x = self.backbone[i](x)
            x_exit = self.exit[i](x)
            x_exit = self.deconv_layers[i](x_exit)
            x_exit = self.final_layer[i](x_exit)
            output.append(x_exit)

        return output

    def init_weights(self, pretrained=''):
        # for k,v in self.state_dict().items():
        #     print(k)
        if os.path.isfile(pretrained):
            logger.info('=> init head deconv weights from normal distribution')

            # for name, m in self.named_parameters():
            #     m.requires_grad = False

            for name, m in self.deconv_layers.named_modules():
                if isinstance(m, nn.ConvTranspose2d):
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    if self.deconv_with_bias:
                        nn.init.constant_(m.bias, 0)
                elif isinstance(m, nn.BatchNorm2d):
                    logger.info('=> init {}.weight as 1'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.constant_(m.weight, 1)
                    nn.init.constant_(m.bias, 0)
            logger.info('=> init head final conv weights from normal distribution')
            for m in self.final_layer.modules():
                if isinstance(m, nn.Conv2d):
                    # nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                    logger.info('=> init {}.weight as normal(0, 0.001)'.format(name))
                    logger.info('=> init {}.bias as 0'.format(name))
                    nn.init.normal_(m.weight, std=0.001)
                    nn.init.constant_(m.bias, 0)

            # for name, m in self.head_deconv_layers.named_parameters():
            #     m.requires_grad = True
            # for name, m in self.head_final_layer.named_parameters():
            #     m.requires_grad = True

            # pretrained_state_dict = torch.load(pretrained)
            logger.info('=> loading pretrained model {}'.format(pretrained))
            # self.load_state_dict(pretrained_state_dict, strict=False)
            checkpoint = torch.load(pretrained)
            dict_trained = checkpoint.copy()
            dict_new = OrderedDict()

            for k,v in self.state_dict().items():
                if 'num_batches_tracked' not in k:
                    if 'backbone_s1.pre' in k:
                        dict_new[k] = dict_trained[k[16:]]
                    elif 'backbone_s1.exit' in k:
                        if len(self.backbone_s1.exit) == 1:
                            dict_new[k] = dict_trained['layer4.0.'+k[19:]]
                        elif len(self.backbone_s1.exit) == 2:
                            if 'exit.0' in k:
                                dict_new[k] = dict_trained['layer3.0.'+k[19:]]
                            elif 'exit.1' in k:
                                dict_new[k] = dict_trained['layer4.0.'+k[19:]]
                        elif len(self.backbone_s1.exit) == 3:
                            if 'exit.0' in k:
                                dict_new[k] = dict_trained['layer2.0.'+k[19:]]
                            elif 'exit.1' in k:
                                dict_new[k] = dict_trained['layer3.0.'+k[19:]]
                            elif 'exit.2' in k:
                                dict_new[k] = dict_trained['layer4.0.'+k[19:]]
                    elif 'deconv' in k or 'final' in k:
                        dict_new[k] = dict_trained[k]
                    else:
                        dict_new[k] = dict_trained[k[12:]]

            # for k,v in dict_new.items():
            #     print(k)
            # if isinstance(checkpoint, OrderedDict):
            #     state_dict = checkpoint
            # elif isinstance(checkpoint, dict) and 'state_dict' in checkpoint:
            #     state_dict_old = checkpoint['state_dict']
            #     state_dict = OrderedDict()
            #     # delete 'module.' because it is saved from DataParallel module

            #     for key in state_dict_old.keys():
            #         if key.startswith('module.'):
            #             # state_dict[key[7:]] = state_dict[key]
            #             # state_dict.pop(key)
            #             state_dict[key[7:]] = state_dict_old[key]
            #         else:
            #             state_dict[key] = state_dict_old[key]
            # else:
            #     raise RuntimeError(
            #         'No state_dict found in checkpoint file {}'.format(pretrained))

            # freeze the backbone parameters
            for k,v in self.named_parameters():
                if 'backbone' in k and 'exit' not in k:
                    v.requires_grad=False
                else:
                    v.requires_grad=True

            self.load_state_dict(dict_new, strict=False)

        else:
            logger.error('=> imagenet pretrained model dose not exist')
            logger.error('=> please download it first')
            raise ValueError('imagenet pretrained model does not exist')


resnet_spec = {18: (BasicBlock, [2, 2, 2, 2]),
               34: (BasicBlock, [3, 4, 6, 3]),
               50: (Bottleneck, [3, 4, 6, 3]),
               101: (Bottleneck, [3, 4, 23, 3]),
               152: (Bottleneck, [3, 8, 36, 3])}

def get_pose_net(cfg, is_train, **kwargs):
    num_layers = cfg.MODEL.EXTRA.NUM_LAYERS
    style = cfg.MODEL.STYLE

    block_class, layers = resnet_spec[num_layers]

    if style == 'caffe':
        block_class = Bottleneck_CAFFE

    model = PoseResNet(block_class, layers, cfg, **kwargs)

    if is_train and cfg.MODEL.INIT_WEIGHTS:
        model.init_weights(cfg.MODEL.PRETRAINED)

    # print("Model obtained!")
    # model.eval()
    # input = torch.rand(1, 3, 384, 384)
    # output = model(input)

    # input_names = ["input"]
    # output_names = ["final_output"]
    # torch.onnx.export(model, input, 
    #                     "/home/slzhang/projects/ETBA/Inference/src/exit_placement/models/posenet_s0.onnx",
    #                     input_names=input_names, output_names=output_names,
    #                     verbose=False,dynamic_axes={
    #                                   'input': {0: 'batch_size'},
    #                                   'final_output': {0: 'batch_size'},
    #                               },opset_version=11)

    return model

def get_pose_net_with_exit(cfg, is_train, start_point, **kwargs):
    num_layers = cfg.MODEL.EXTRA.NUM_LAYERS
    style = cfg.MODEL.STYLE

    block_class, layers = resnet_spec[num_layers]

    if style == 'caffe':
        block_class = Bottleneck_CAFFE

    model = PoseResNetwthExit(block_class, layers, cfg, start_point, **kwargs)

    if is_train and cfg.MODEL.INIT_WEIGHTS:
        pass
        # model.init_weights(cfg.MODEL.PRETRAINED)
        # model.init_weights(cfg.MODEL.PRETRAINED_WITH_HEAD)

    print("Model obtained!")
    # model.eval()
    # input = torch.rand(1, 3, 384, 384)
    # output = model(input)

    # input_names = ["input"]
    # output_names = ["final_output"]
    # torch.onnx.export(model, input, 
    #                     "/home/slzhang/projects/ETBA/Train/human-pose-estimation.pytorch/posenet_with_exit.onnx",
    #                     input_names=input_names, output_names=output_names,
    #                     verbose=False,dynamic_axes={
    #                                   'input': {0: 'batch_size'},
    #                                   'final_output': {0: 'batch_size'},
    #                               },opset_version=11)

    return model

def get_pose_net_with_only_exit(cfg, is_train, start_point, **kwargs):
    num_layers = cfg.MODEL.EXTRA.NUM_LAYERS
    style = cfg.MODEL.STYLE

    block_class, layers = resnet_spec[num_layers]

    if style == 'caffe':
        block_class = Bottleneck_CAFFE

    model = PoseResNetwthOnlyExit(block_class, layers, cfg, start_point, **kwargs)

    if is_train and cfg.MODEL.INIT_WEIGHTS:
        # model.init_weights(cfg.MODEL.PRETRAINED)
        model.init_weights(cfg.MODEL.PRETRAINED_WITH_HEAD)

    print("Model obtained!")

    return model

def get_pose_net_with_multi_exit(cfg, is_train, exit_list, **kwargs):
    num_layers = cfg.MODEL.EXTRA.NUM_LAYERS
    style = cfg.MODEL.STYLE

    block_class, layers = resnet_spec[num_layers]

    if style == 'caffe':
        block_class = Bottleneck_CAFFE

    model = PoseResNetwthMultiExit(block_class, layers, cfg, exit_list, **kwargs)

    # for k,v in model.backbone[1].named_parameters():
    #     print(k)

    # baseModel = torch.nn.Sequential(*(list(model.backbone[1].modules())[:-1]))
    # for k,v in baseModel[0].named_parameters():
    #     print(k)

    # if is_train and cfg.MODEL.INIT_WEIGHTS:
    #     # model.init_weights(cfg.MODEL.PRETRAINED)
    #     model.init_weights(cfg.MODEL.PRETRAINED_WITH_HEAD)

    print("Model obtained!")

    return model

def get_children(model: torch.nn.Module):
    # get children form model!
    children = list(model.children())
    flatt_children = []
    if children == []:
        # if model has no children; model is last child! :O
        return model
    else:
    # look for children from children... to the last child!
        for child in children:
            try:
                flatt_children.extend(get_children(child))
            except TypeError:
                flatt_children.append(get_children(child))
    return flatt_children