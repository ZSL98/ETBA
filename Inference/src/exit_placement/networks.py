import math

import torch
from torch import Tensor
import torch.nn as nn
from typing import Type, Any, Callable, Union, List, Optional

import torch.nn.functional as F
from modules.wasp import build_wasp
from modules.decoder import build_decoder
from modules.backbone import build_backbone

BN_MOMENTUM = 0.1

def fc_layer(size_in, size_out):
    layer = nn.Sequential(
        nn.Linear(size_in, size_out),
        nn.BatchNorm1d(size_out),
        nn.ReLU()
    )
    return layer

def conv3x3(in_planes: int, out_planes: int, stride: int = 1, groups: int = 1, dilation: int = 1) -> nn.Conv2d:
    """3x3 convolution with padding"""
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                     padding=dilation, groups=groups, bias=False, dilation=dilation)


def conv1x1(in_planes: int, out_planes: int, stride: int = 1) -> nn.Conv2d:
    """1x1 convolution"""
    return nn.Conv2d(in_planes, out_planes, kernel_size=1, stride=stride, bias=False)


class exit_resnet_s1(nn.Module):
    def __init__(self, num_classes: int = 1000):
        super(exit_resnet_s1, self).__init__()
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.conv1x1_exit = conv1x1(256, 512)
        self.exit = self._make_complex_exit(64)
        self.inplanes = 64
        self.fc_exit = nn.Linear(512, num_classes)

    def _make_complex_exit(self, planes: int) -> nn.Sequential:
        layers = []
        self.inplanes = planes * Bottleneck.expansion
        layers.append(Bottleneck(self.inplanes, planes))
        return nn.Sequential(*layers)
    
    def forward(self, x):
        x_exit = self.exit(x)
        x_exit = self.conv1x1_exit(x_exit)
        x_exit = self.avgpool(x_exit)
        x_exit = torch.flatten(x_exit, 1)
        x_exit = self.fc_exit(x_exit)

        return x_exit

class exit_resnet_s2(nn.Module):
    def __init__(self, num_classes: int = 1000):
        super(exit_resnet_s2, self).__init__()
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        # self.conv1x1_exit = conv1x1(256, 512)
        self.exit = self._make_complex_exit(128)
        self.inplanes = 64
        self.fc_exit = nn.Linear(512, num_classes)

    def _make_complex_exit(self, planes: int) -> nn.Sequential:
        layers = []
        self.inplanes = planes * Bottleneck.expansion
        layers.append(Bottleneck(self.inplanes, planes))
        return nn.Sequential(*layers)
    
    def forward(self, x):
        x_exit = self.exit(x)
        # x_exit = self.conv1x1_exit(x_exit)
        x_exit = self.avgpool(x_exit)
        x_exit = torch.flatten(x_exit, 1)
        x_exit = self.fc_exit(x_exit)

        return x_exit

class exit_resnet_s3(nn.Module):
    def __init__(self, num_classes: int = 1000):
        super(exit_resnet_s3, self).__init__()
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        # self.conv1x1_exit = conv1x1(256, 512)
        self.exit = self._make_complex_exit(256)
        self.inplanes = 64
        self.fc_exit = nn.Linear(1024, num_classes)

    def _make_complex_exit(self, planes: int) -> nn.Sequential:
        layers = []
        self.inplanes = planes * Bottleneck.expansion
        layers.append(Bottleneck(self.inplanes, planes))
        return nn.Sequential(*layers)
    
    def forward(self, x):
        x_exit = self.exit(x)
        x_exit = self.avgpool(x_exit)
        x_exit = torch.flatten(x_exit, 1)
        x_exit = self.fc_exit(x_exit)

        return x_exit

class exit_resnet_s4(nn.Module):
    def __init__(self, num_classes: int = 1000):
        super(exit_resnet_s4, self).__init__()
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.conv1x1_exit = conv1x1(256, 512)
        self.exit = self._make_complex_exit(64)
        self.inplanes = 64
        self.fc_exit = nn.Linear(512, num_classes)

    def _make_complex_exit(self, planes: int) -> nn.Sequential:
        layers = []
        self.inplanes = planes * Bottleneck.expansion
        layers.append(Bottleneck(self.inplanes, planes))
        return nn.Sequential(*layers)
    
    def forward(self, x):
        x_exit = self.exit(x)
        x_exit = self.conv1x1_exit(x_exit)
        x_exit = self.avgpool(x_exit)
        x_exit = torch.flatten(x_exit, 1)
        x_exit = self.fc_exit(x_exit)

        return x_exit


class BasicBlock(nn.Module):
    expansion: int = 1

    def __init__(
        self,
        inplanes: int,
        planes: int,
        stride: int = 1,
        downsample: Optional[nn.Module] = None,
        groups: int = 1,
        base_width: int = 64,
        dilation: int = 1,
        norm_layer: Optional[Callable[..., nn.Module]] = None
    ) -> None:
        super(BasicBlock, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        if groups != 1 or base_width != 64:
            raise ValueError('BasicBlock only supports groups=1 and base_width=64')
        if dilation > 1:
            raise NotImplementedError("Dilation > 1 not supported in BasicBlock")
        # Both self.conv1 and self.downsample layers downsample the input when stride != 1
        self.conv1 = conv3x3(inplanes, planes, stride)
        self.bn1 = norm_layer(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(planes, planes)
        self.bn2 = norm_layer(planes)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x: Tensor) -> Tensor:
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            identity = self.downsample(x)

        out += identity
        out = self.relu(out)

        return out


class Bottleneck(nn.Module):
    # Bottleneck in torchvision places the stride for downsampling at 3x3 convolution(self.conv2)
    # while original implementation places the stride at the first 1x1 convolution(self.conv1)
    # according to "Deep residual learning for image recognition"https://arxiv.org/abs/1512.03385.
    # This variant is also known as ResNet V1.5 and improves accuracy according to
    # https://ngc.nvidia.com/catalog/model-scripts/nvidia:resnet_50_v1_5_for_pytorch.

    expansion: int = 4

    def __init__(
        self,
        inplanes: int,
        planes: int,
        stride: int = 1,
        downsample: Optional[nn.Module] = None,
        groups: int = 1,
        base_width: int = 64,
        dilation: int = 1,
        norm_layer: Optional[Callable[..., nn.Module]] = None
    ) -> None:
        super(Bottleneck, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        width = int(planes * (base_width / 64.)) * groups
        # Both self.conv2 and self.downsample layers downsample the input when stride != 1
        self.conv1 = conv1x1(inplanes, width)
        self.bn1 = norm_layer(width)
        self.conv2 = conv3x3(width, width, stride, groups, dilation)
        self.bn2 = norm_layer(width)
        self.conv3 = conv1x1(width, planes * self.expansion)
        self.bn3 = norm_layer(planes * self.expansion)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x: Tensor) -> Tensor:
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            identity = self.downsample(x)

        out += identity
        out = self.relu(out)

        return out

def model_split(layers, start_point, end_point):
    s1_pre_layer = [0] * len(layers)
    s1_post_layer = [0] * len(layers)
    s2_layer = [0] * len(layers)
    add_pos = 0
    for i in range(start_point):
        if s1_pre_layer[add_pos] == layers[add_pos]:
            add_pos = add_pos + 1
        s1_pre_layer[add_pos] = s1_pre_layer[add_pos] + 1
    add_pos = 0
    for i in range(end_point):
        if s1_post_layer[add_pos] == layers[add_pos]:
            add_pos = add_pos + 1
        s1_post_layer[add_pos] = s1_post_layer[add_pos] + 1
    s2_layer = [i-j for i, j in zip(layers, s1_post_layer)]
    s1_post_layer = [i-j for i, j in zip(s1_post_layer, s1_pre_layer)]

    return s1_pre_layer, s1_post_layer, s2_layer


class resnet_s1(nn.Module):
    def __init__(
        self,
        block: Type[Union[BasicBlock, Bottleneck]] = Bottleneck,
        layers: List[int] = [3, 4, 23, 3],
        num_classes: int = 1000,
        start_point: int = 1,
        end_point: int = 1,
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        simple_exit: bool = True,
        replace_stride_with_dilation: Optional[List[bool]] = None,
        norm_layer: Optional[Callable[..., nn.Module]] = None
    ) -> None:
        super(resnet_s1, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        self._norm_layer = norm_layer

        self.inplanes = 64
        self.dilation = 1
        if replace_stride_with_dilation is None:
            # each element in the tuple indicates if we should replace
            # the 2x2 stride with a dilated convolution instead
            replace_stride_with_dilation = [False, False, False]
        if len(replace_stride_with_dilation) != 3:
            raise ValueError("replace_stride_with_dilation should be None "
                             "or a 3-element tuple, got {}".format(replace_stride_with_dilation))
        self.num_classes = num_classes
        self.groups = groups
        self.base_width = width_per_group
        self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=7, stride=2, padding=3,
                               bias=False)
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        self.pre_layer, self.post_layer, _ = model_split(layers, start_point, end_point)
        print(self.pre_layer)
        print(self.post_layer)
        print(_)
        self.pre_layer1 = self._make_layer(block, 64, self.pre_layer[0])
        self.pre_layer2 = self._make_layer(block, 128, self.pre_layer[1], stride=2,
                                       dilate=replace_stride_with_dilation[0])
        self.pre_layer3 = self._make_layer(block, 256, self.pre_layer[2], stride=2,
                                       dilate=replace_stride_with_dilation[1])
        self.pre_layer4 = self._make_layer(block, 512, self.pre_layer[3], stride=2,
                                       dilate=replace_stride_with_dilation[2])

        self.post_layer1 = self._make_layer(block, 64, self.post_layer[0], pre_or_not=False, layer_idx=0)
        self.post_layer2 = self._make_layer(block, 128, self.post_layer[1], stride=2,
                                       dilate=replace_stride_with_dilation[0], pre_or_not=False,
                                       layer_idx=1)
        self.post_layer3 = self._make_layer(block, 256, self.post_layer[2], stride=2,
                                       dilate=replace_stride_with_dilation[1], pre_or_not=False,
                                       layer_idx=2)
        self.post_layer4 = self._make_layer(block, 512, self.post_layer[3], stride=2,
                                       dilate=replace_stride_with_dilation[2], pre_or_not=False,
                                       layer_idx=3)

        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512 * block.expansion, num_classes)
        # self.conv1x1_exit = conv1x1(256, 512)
        # self.bottleblock = Bottleneck(256, 64)


        if simple_exit:
            if self.pre_layer[1] == 0:
                self.exit = self._make_simple_exit(64)
                self.fc_exit = nn.Linear(64 * Bottleneck.expansion, num_classes)
            elif self.pre_layer[2] == 0:
                self.exit = self._make_simple_exit(128)
                self.fc_exit = nn.Linear(128 * Bottleneck.expansion, num_classes)
            elif self.pre_layer[3] == 0:
                self.exit = self._make_simple_exit(256)
                self.fc_exit = nn.Linear(256 * Bottleneck.expansion, num_classes)
            else:
                self.exit = self._make_simple_exit(512)
                self.fc_exit = nn.Linear(512 * Bottleneck.expansion, num_classes)
        else:
            if self.pre_layer[1] == 0:
                self.exit = self._make_complex_exit(1, stride=2)
            elif self.pre_layer[2] == 0:
                self.exit = self._make_complex_exit(2, stride=2)
            elif self.pre_layer[3] == 0:
                self.exit = self._make_complex_exit(3, stride=2)
            else:
                self.exit = self._make_complex_exit(4, stride=2)
            self.fc_exit = nn.Linear(512 * Bottleneck.expansion, num_classes)


        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, (nn.BatchNorm2d, nn.GroupNorm)):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

        # Zero-initialize the last BN in each residual branch,
        # so that the residual branch starts with zeros, and each residual block behaves like an identity.
        # This improves the model by 0.2~0.3% according to https://arxiv.org/abs/1706.02677
        if zero_init_residual:
            for m in self.modules():
                if isinstance(m, Bottleneck):
                    nn.init.constant_(m.bn3.weight, 0)  # type: ignore[arg-type]
                elif isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)  # type: ignore[arg-type]

    def _make_complex_exit(self, layer: int, stride: int = 1) -> nn.Sequential:
        layers = []
        norm_layer = self._norm_layer
        previous_dilation = self.dilation
        if layer < 1:
            downsample_1 = nn.Sequential(
                conv1x1(64, 256, stride),
                norm_layer(256),
            )
            layers.append(Bottleneck(128, 64, stride, downsample_1, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        if layer < 2:
            downsample_2 = nn.Sequential(
                conv1x1(256, 512, stride),
                norm_layer(512),
            )
            layers.append(Bottleneck(256, 128, stride, downsample_2, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        if layer < 3:
            downsample_3 = nn.Sequential(
                conv1x1(512, 1024, stride),
                norm_layer(1024),
            )
            layers.append(Bottleneck(512, 256, stride, downsample_3, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        if layer < 4:
            downsample_4 = nn.Sequential(
                conv1x1(1024, 2048, stride),
                norm_layer(2048),
            )
            layers.append(Bottleneck(1024, 512, stride, downsample_4, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        return nn.Sequential(*layers)


    def _make_simple_exit(self, planes: int) -> nn.Sequential:
        layers = []
        norm_layer = self._norm_layer
        self.inplanes = planes * Bottleneck.expansion
        layers.append(Bottleneck(self.inplanes, planes, groups=self.groups,
                                base_width=self.base_width, dilation=self.dilation,
                                norm_layer=norm_layer))
        return nn.Sequential(*layers)


    def _make_layer(self, block: Type[Union[BasicBlock, Bottleneck]], planes: int, blocks: int,
                    stride: int = 1, dilate: bool = False, pre_or_not: bool = True,
                    layer_idx: int = 0) -> nn.Sequential:
        if blocks == 0:
            layers = []
            return nn.Sequential(*layers)
        norm_layer = self._norm_layer
        downsample = None
        previous_dilation = self.dilation
        if dilate:
            self.dilation *= stride
            stride = 1
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )

        layers = []
        if pre_or_not:
            layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                            self.base_width, previous_dilation, norm_layer))
            self.inplanes = planes * block.expansion
            for _ in range(1, blocks):
                layers.append(block(self.inplanes, planes, groups=self.groups,
                                    base_width=self.base_width, dilation=self.dilation,
                                    norm_layer=norm_layer))
        else:
            if self.pre_layer[layer_idx] == 0:
                blocks = blocks - 1
                self.inplanes = planes * 2
                downsample = nn.Sequential(
                    conv1x1(self.inplanes, planes * block.expansion, stride),
                    norm_layer(planes * block.expansion),
                )
                layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                            self.base_width, previous_dilation, norm_layer))
            self.inplanes = planes * block.expansion
            for _ in range(0, blocks):
                layers.append(block(self.inplanes, planes, groups=self.groups,
                                    base_width=self.base_width, dilation=self.dilation,
                                    norm_layer=norm_layer))           

        return nn.Sequential(*layers)

    def _forward_impl(self, x: Tensor) -> Tensor:
        # See note [TorchScript super()]
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        # pre-network
        x_fork = self.pre_layer1(x)
        x_fork = self.pre_layer2(x_fork)
        x_fork = self.pre_layer3(x_fork)
        x_fork = self.pre_layer4(x_fork)

        # exit branch
        x_exit = self.exit(x_fork)
        # x_exit = self.conv1x1_exit(x_exit)
        x_exit = self.avgpool(x_exit)
        x_exit = torch.flatten(x_exit, 1)
        x_exit = self.fc_exit(x_exit)

        # backbone continue
        x_c = self.post_layer1(x_fork)
        x_c = self.post_layer2(x_c)
        x_c = self.post_layer3(x_c)
        x_c = self.post_layer4(x_c)

        return x_c, x_exit

    def forward(self, x: Tensor) -> Tensor:
        return self._forward_impl(x)

class resnet_s2(nn.Module):
    def __init__(
        self,
        block: Type[Union[BasicBlock, Bottleneck]] = Bottleneck,
        layers: List[int] = [3, 4, 23, 3],
        start_point: int = 1,
        end_point: int = 1,
        num_classes: int = 1000,
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        replace_stride_with_dilation: Optional[List[bool]] = None,
        norm_layer: Optional[Callable[..., nn.Module]] = None
    ) -> None:
        super(resnet_s2, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        self._norm_layer = norm_layer

        self.inplanes = 64
        self.dilation = 1
        if replace_stride_with_dilation is None:
            # each element in the tuple indicates if we should replace
            # the 2x2 stride with a dilated convolution instead
            replace_stride_with_dilation = [False, False, False]
        if len(replace_stride_with_dilation) != 3:
            raise ValueError("replace_stride_with_dilation should be None "
                             "or a 3-element tuple, got {}".format(replace_stride_with_dilation))
        self.groups = groups
        self.base_width = width_per_group
        self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=7, stride=2, padding=3,
                               bias=False)
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        _pre_layer, _post_layer, self.s2_layer = model_split(layers, start_point, end_point)
        self.s1_layer = [i+j for i, j in zip(_pre_layer, _post_layer)]
        self.layer1 = self._make_layer(block, 64, self.s2_layer[0], layer_idx=0)
        self.layer2 = self._make_layer(block, 128, self.s2_layer[1], stride=2,
                                       dilate=replace_stride_with_dilation[0], layer_idx=1)
        self.layer3 = self._make_layer(block, 256, self.s2_layer[2], stride=2,
                                       dilate=replace_stride_with_dilation[1], layer_idx=2)
        self.layer4 = self._make_layer(block, 512, self.s2_layer[3], stride=2,
                                       dilate=replace_stride_with_dilation[2], layer_idx=3)
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512 * block.expansion, num_classes)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, (nn.BatchNorm2d, nn.GroupNorm)):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

        # Zero-initialize the last BN in each residual branch,
        # so that the residual branch starts with zeros, and each residual block behaves like an identity.
        # This improves the model by 0.2~0.3% according to https://arxiv.org/abs/1706.02677
        if zero_init_residual:
            for m in self.modules():
                if isinstance(m, Bottleneck):
                    nn.init.constant_(m.bn3.weight, 0)  # type: ignore[arg-type]
                elif isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)  # type: ignore[arg-type]

    def _make_layer(self, block: Type[Union[BasicBlock, Bottleneck]], planes: int, blocks: int,
                    stride: int = 1, dilate: bool = False, layer_idx: int = 0) -> nn.Sequential:
        if blocks == 0:
            layers = []
            return nn.Sequential(*layers)
        norm_layer = self._norm_layer
        downsample = None
        previous_dilation = self.dilation
        if dilate:
            self.dilation *= stride
            stride = 1
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )

        layers = []
        if self.s1_layer[layer_idx] == 0:
            blocks = blocks - 1
            self.inplanes = planes * 2
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )
            layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                                self.base_width, previous_dilation, norm_layer))
        self.inplanes = planes * block.expansion
        for _ in range(0, blocks):
            layers.append(block(self.inplanes, planes, groups=self.groups,
                                base_width=self.base_width, dilation=self.dilation,
                                norm_layer=norm_layer))

        return nn.Sequential(*layers)

    def _forward_impl(self, x: Tensor) -> Tensor:
        # See note [TorchScript super()]

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        x = self.fc(x)

        return x

    def forward(self, x: Tensor) -> Tensor:
        return self._forward_impl(x)

class backbone_s1(nn.Module):
    def __init__(
        self,
        block: Type[Union[BasicBlock, Bottleneck]] = Bottleneck,
        layers: List[int] = [3, 4, 23, 3],
        num_classes: int = 1000,
        start_point: int = 1,
        end_point: int = 1,
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        simple_exit: bool = True,
        replace_stride_with_dilation: Optional[List[bool]] = None,
        norm_layer: Optional[Callable[..., nn.Module]] = None
    ) -> None:
        super(backbone_s1, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        self._norm_layer = norm_layer

        self.inplanes = 64
        self.dilation = 1
        if replace_stride_with_dilation is None:
            # each element in the tuple indicates if we should replace
            # the 2x2 stride with a dilated convolution instead
            replace_stride_with_dilation = [False, False, False]
        if len(replace_stride_with_dilation) != 3:
            raise ValueError("replace_stride_with_dilation should be None "
                             "or a 3-element tuple, got {}".format(replace_stride_with_dilation))
        self.num_classes = num_classes
        self.groups = groups
        self.base_width = width_per_group
        self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=7, stride=2, padding=3,
                               bias=False)
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        self.pre_layer, self.post_layer, _ = model_split(layers, start_point, end_point)
        print(self.pre_layer)
        print(self.post_layer)
        print(_)
        self.pre_layer1 = self._make_layer(block, 64, self.pre_layer[0])
        self.pre_layer2 = self._make_layer(block, 128, self.pre_layer[1], stride=2,
                                       dilate=replace_stride_with_dilation[0])
        self.pre_layer3 = self._make_layer(block, 256, self.pre_layer[2], stride=2,
                                       dilate=replace_stride_with_dilation[1])
        self.pre_layer4 = self._make_layer(block, 512, self.pre_layer[3], stride=2,
                                       dilate=replace_stride_with_dilation[2])

        self.post_layer1 = self._make_layer(block, 64, self.post_layer[0], pre_or_not=False, layer_idx=0)
        self.post_layer2 = self._make_layer(block, 128, self.post_layer[1], stride=2,
                                       dilate=replace_stride_with_dilation[0], pre_or_not=False,
                                       layer_idx=1)
        self.post_layer3 = self._make_layer(block, 256, self.post_layer[2], stride=2,
                                       dilate=replace_stride_with_dilation[1], pre_or_not=False,
                                       layer_idx=2)
        self.post_layer4 = self._make_layer(block, 512, self.post_layer[3], stride=2,
                                       dilate=replace_stride_with_dilation[2], pre_or_not=False,
                                       layer_idx=3)

        if self.pre_layer[1] == 0:
            self.exit = self._make_complex_exit(1, stride=2)
        elif self.pre_layer[2] == 0:
            self.exit = self._make_complex_exit(2, stride=2)
        elif self.pre_layer[3] == 0:
            self.exit = self._make_complex_exit(3, stride=2)
        else:
            self.exit = self._make_complex_exit(4, stride=2)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, (nn.BatchNorm2d, nn.GroupNorm)):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

        # Zero-initialize the last BN in each residual branch,
        # so that the residual branch starts with zeros, and each residual block behaves like an identity.
        # This improves the model by 0.2~0.3% according to https://arxiv.org/abs/1706.02677
        if zero_init_residual:
            for m in self.modules():
                if isinstance(m, Bottleneck):
                    nn.init.constant_(m.bn3.weight, 0)  # type: ignore[arg-type]
                elif isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)  # type: ignore[arg-type]

    def _make_complex_exit(self, layer: int, stride: int = 1) -> nn.Sequential:
        layers = []
        norm_layer = self._norm_layer
        previous_dilation = self.dilation
        if layer < 1:
            downsample_1 = nn.Sequential(
                conv1x1(64, 256, stride),
                norm_layer(256),
            )
            layers.append(Bottleneck(128, 64, stride, downsample_1, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        if layer < 2:
            downsample_2 = nn.Sequential(
                conv1x1(256, 512, stride),
                norm_layer(512),
            )
            layers.append(Bottleneck(256, 128, stride, downsample_2, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        if layer < 3:
            downsample_3 = nn.Sequential(
                conv1x1(512, 1024, stride),
                norm_layer(1024),
            )
            layers.append(Bottleneck(512, 256, stride, downsample_3, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        if layer < 4:
            downsample_4 = nn.Sequential(
                conv1x1(1024, 2048, stride),
                norm_layer(2048),
            )
            layers.append(Bottleneck(1024, 512, stride, downsample_4, self.groups,
                        self.base_width, previous_dilation, norm_layer))

        return nn.Sequential(*layers)


    def _make_layer(self, block: Type[Union[BasicBlock, Bottleneck]], planes: int, blocks: int,
                    stride: int = 1, dilate: bool = False, pre_or_not: bool = True,
                    layer_idx: int = 0) -> nn.Sequential:
        if blocks == 0:
            layers = []
            return nn.Sequential(*layers)
        norm_layer = self._norm_layer
        downsample = None
        previous_dilation = self.dilation
        if dilate:
            self.dilation *= stride
            stride = 1
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )

        layers = []
        if pre_or_not:
            layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                            self.base_width, previous_dilation, norm_layer))
            self.inplanes = planes * block.expansion
            for _ in range(1, blocks):
                layers.append(block(self.inplanes, planes, groups=self.groups,
                                    base_width=self.base_width, dilation=self.dilation,
                                    norm_layer=norm_layer))
        else:
            if self.pre_layer[layer_idx] == 0:
                blocks = blocks - 1
                self.inplanes = planes * 2
                downsample = nn.Sequential(
                    conv1x1(self.inplanes, planes * block.expansion, stride),
                    norm_layer(planes * block.expansion),
                )
                layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                            self.base_width, previous_dilation, norm_layer))
            self.inplanes = planes * block.expansion
            for _ in range(0, blocks):
                layers.append(block(self.inplanes, planes, groups=self.groups,
                                    base_width=self.base_width, dilation=self.dilation,
                                    norm_layer=norm_layer))           

        return nn.Sequential(*layers)

    def _forward_impl(self, x: Tensor) -> Tensor:
        # See note [TorchScript super()]
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        # pre-network
        x_fork = self.pre_layer1(x)
        x_fork = self.pre_layer2(x_fork)
        x_fork = self.pre_layer3(x_fork)
        x_fork = self.pre_layer4(x_fork)

        # exit branch
        x_exit = self.exit(x_fork)

        # backbone continue
        x_c = self.post_layer1(x_fork)
        x_c = self.post_layer2(x_c)
        x_c = self.post_layer3(x_c)
        x_c = self.post_layer4(x_c)

        return x_c, x_exit

    def forward(self, x: Tensor) -> Tensor:
        return self._forward_impl(x)

class backbone_s2(nn.Module):
    def __init__(
        self,
        block: Type[Union[BasicBlock, Bottleneck]] = Bottleneck,
        layers: List[int] = [3, 4, 23, 3],
        start_point: int = 1,
        end_point: int = 1,
        num_classes: int = 1000,
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        replace_stride_with_dilation: Optional[List[bool]] = None,
        norm_layer: Optional[Callable[..., nn.Module]] = None
    ) -> None:
        super(backbone_s2, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        self._norm_layer = norm_layer

        self.inplanes = 64
        self.dilation = 1
        if replace_stride_with_dilation is None:
            # each element in the tuple indicates if we should replace
            # the 2x2 stride with a dilated convolution instead
            replace_stride_with_dilation = [False, False, False]
        if len(replace_stride_with_dilation) != 3:
            raise ValueError("replace_stride_with_dilation should be None "
                             "or a 3-element tuple, got {}".format(replace_stride_with_dilation))
        self.groups = groups
        self.base_width = width_per_group
        self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=7, stride=2, padding=3,
                               bias=False)
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        _pre_layer, _post_layer, self.s2_layer = model_split(layers, start_point, end_point)
        self.s1_layer = [i+j for i, j in zip(_pre_layer, _post_layer)]
        self.layer1 = self._make_layer(block, 64, self.s2_layer[0], layer_idx=0)
        self.layer2 = self._make_layer(block, 128, self.s2_layer[1], stride=2,
                                       dilate=replace_stride_with_dilation[0], layer_idx=1)
        self.layer3 = self._make_layer(block, 256, self.s2_layer[2], stride=2,
                                       dilate=replace_stride_with_dilation[1], layer_idx=2)
        self.layer4 = self._make_layer(block, 512, self.s2_layer[3], stride=2,
                                       dilate=replace_stride_with_dilation[2], layer_idx=3)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, (nn.BatchNorm2d, nn.GroupNorm)):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

        # Zero-initialize the last BN in each residual branch,
        # so that the residual branch starts with zeros, and each residual block behaves like an identity.
        # This improves the model by 0.2~0.3% according to https://arxiv.org/abs/1706.02677
        if zero_init_residual:
            for m in self.modules():
                if isinstance(m, Bottleneck):
                    nn.init.constant_(m.bn3.weight, 0)  # type: ignore[arg-type]
                elif isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)  # type: ignore[arg-type]

    def _make_layer(self, block: Type[Union[BasicBlock, Bottleneck]], planes: int, blocks: int,
                    stride: int = 1, dilate: bool = False, layer_idx: int = 0) -> nn.Sequential:
        if blocks == 0:
            layers = []
            return nn.Sequential(*layers)
        norm_layer = self._norm_layer
        downsample = None
        previous_dilation = self.dilation
        if dilate:
            self.dilation *= stride
            stride = 1
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )

        layers = []
        if self.s1_layer[layer_idx] == 0:
            blocks = blocks - 1
            self.inplanes = planes * 2
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )
            layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                                self.base_width, previous_dilation, norm_layer))
        self.inplanes = planes * block.expansion
        for _ in range(0, blocks):
            layers.append(block(self.inplanes, planes, groups=self.groups,
                                base_width=self.base_width, dilation=self.dilation,
                                norm_layer=norm_layer))

        return nn.Sequential(*layers)

    def _forward_impl(self, x: Tensor) -> Tensor:
        # See note [TorchScript super()]

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        return x

    def forward(self, x: Tensor) -> Tensor:
        return self._forward_impl(x)


class posenet_s1(nn.Module):
    def __init__(self, start_point, end_point):
        super(posenet_s1, self).__init__()
        self.deconv_with_bias = False
        self.start_point = start_point
        self.end_point = end_point
        self.backbone_s1 = backbone_s1(start_point=self.start_point, end_point=self.end_point)

        self.inplanes = 2048
        self.head_deconv_layers = self._make_deconv_layer(
            3,
            [256, 256, 256],
            [4, 4, 4],
        )

        self.head_final_layer = nn.Conv2d(
            in_channels=256,
            out_channels=16,
            kernel_size=1,
            stride=1,
            padding=1
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
            layers.append(nn.BatchNorm2d(planes, momentum=0.1))
            layers.append(nn.ReLU(inplace=True))
            self.inplanes = planes

        return nn.Sequential(*layers)

    def forward(self, input):
        x, x_exit = self.backbone_s1(input)
        x_exit = self.head_deconv_layers(x_exit)
        x_exit = self.head_final_layer(x_exit)

        return x, x_exit

class posenet_s2(nn.Module):
    def __init__(self, start_point, end_point):
        super(posenet_s2, self).__init__()
        self.deconv_with_bias = False
        self.start_point = start_point
        self.end_point = end_point
        self.backbone_s2 = backbone_s2(start_point=self.start_point, end_point=self.end_point)

        self.inplanes = 2048
        self.deconv_layers = self._make_deconv_layer(
            3,
            [256, 256, 256],
            [4, 4, 4],
        )

        self.final_layer = nn.Conv2d(
            in_channels=256,
            out_channels=16,
            kernel_size=1,
            stride=1,
            padding=1
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
            layers.append(nn.BatchNorm2d(planes, momentum=0.1))
            layers.append(nn.ReLU(inplace=True))
            self.inplanes = planes

        return nn.Sequential(*layers)

    def forward(self, input):
        x = self.backbone_s2(input)
        x = self.deconv_layers(x)
        x = self.final_layer(x)

        return x

class PoseResNet(nn.Module):

    def __init__(self):
        self.inplanes = 64
        self.deconv_with_bias = False
        layers = [3, 4, 23, 3]
        super(PoseResNet, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3,
                               bias=False)
        self.bn1 = nn.BatchNorm2d(64, momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(Bottleneck, 64, layers[0])
        self.layer2 = self._make_layer(Bottleneck, 128, layers[1], stride=2)
        self.layer3 = self._make_layer(Bottleneck, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(Bottleneck, 512, layers[3], stride=2)

        # used for deconv layers
        self.deconv_layers = self._make_deconv_layer(
            3,
            [256, 256, 256],
            [4, 4, 4],
        )

        self.final_layer = nn.Conv2d(
            in_channels=256,
            out_channels=16,
            kernel_size=1,
            stride=1,
            padding=1 if 1 == 3 else 0
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