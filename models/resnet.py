import torch
import torch.nn as nn
from models.resnet_utils import conv1x1, BasicBlock, Bottleneck
from torchsummary import summary


class ResNet(nn.Module):

    def __init__(self, block, layers, num_classes=102, zero_init_residual=False,
                 groups=1, width_per_group=64, replace_stride_with_dilation=None,
                 norm_layer=None):
        super(ResNet, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        # have projector or not    
        self.have_prj = False

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
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2,
                                       dilate=replace_stride_with_dilation[0])

        self.layer3 = self._make_layer(block, 256, layers[2], stride=2,
                                       dilate=replace_stride_with_dilation[1])         
        self.layer4a = self._make_layer(block, 256, layers[3], stride=2,
                                       dilate=replace_stride_with_dilation[2])
        self.layer4b = self._make_layer(block, 256, layers[3], stride=2,
                                       dilate=replace_stride_with_dilation[2])

        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.dropout = nn.Dropout(0.4, inplace=False)
        self.fca = nn.Linear(1024, 512)
        self.fcb = nn.Linear(1024, 512)             
        self.fc1 = nn.Linear(512, 3)
        self.fc2 = nn.Linear(512, 4)

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
                    nn.init.constant_(m.bn3.weight, 0)
                elif isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)

    def _make_layer(self, block, planes, blocks, stride=1, dilate=False):
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
        layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                            self.base_width, previous_dilation, norm_layer))
        self.inplanes = planes * block.expansion
        if self.inplanes == 2048:  # Check the current number of channels
            self.inplanes = 1024  # Set it to 1024 for layer4b

        for _ in range(1, blocks):
            layers.append(block(self.inplanes, planes, groups=self.groups,
                                base_width=self.base_width, dilation=self.dilation,
                                norm_layer=norm_layer))

        return nn.Sequential(*layers)

    def _forward_impl(self, x):
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)

        birads = self.layer4a(x)
        density = self.layer4b(x)
        birads = self.avgpool(birads)
        density = self.avgpool(density)
        birads = torch.flatten(birads, 1)
        density = torch.flatten(density, 1)

        birads = self.dropout(birads)
        density = self.dropout(density)

        birads = self.fca(birads)
        density = self.fcb(density)
        birads = self.fc1(birads)

        density = self.fc2(density)
        return None, birads, density

    def forward(self, x):
        return self._forward_impl(x)


def _resnet(block, layers, pretrained, pth_url, **kwargs):
    model = ResNet(block, layers, **kwargs)
    if pretrained:
        pretrained_dict = torch.hub.load_state_dict_from_url(pth_url)
        del pretrained_dict['fc.weight']
        del pretrained_dict['fc.bias']
        model_dict = model.state_dict()
        pretrained_dict = {k: v for k, v in pretrained_dict.items() if (k in model_dict)}
        model_dict.update(pretrained_dict)
        model.load_state_dict(model_dict)
    return model


def resnet50(pth_url, pretrained=False, **kwargs):
    return _resnet(Bottleneck, [3, 4, 6, 3], pretrained, pth_url, **kwargs)


def resnet101(pth_url, pretrained=False, **kwargs):
    return _resnet(Bottleneck, [3, 4, 23, 3], pretrained, pth_url, **kwargs)


def resnet152(pth_url, pretrained=False, **kwargs):
    return _resnet(Bottleneck, [3, 8, 36, 3], pretrained, pth_url, **kwargs)


def resnext50_32x4d(pth_url, pretrained=False, **kwargs):
    kwargs['groups'] = 32
    kwargs['width_per_group'] = 4
    return _resnet(Bottleneck, [3, 4, 6, 3], pretrained, pth_url, **kwargs)


def resnext101_32x8d(pth_url, pretrained=False, **kwargs):
    kwargs['groups'] = 32
    kwargs['width_per_group'] = 8
    return _resnet(Bottleneck, [3, 4, 23, 3], pretrained, pth_url, **kwargs)


def resnext101_64x4d(pth_url, pretrained=False, **kwargs):
    kwargs['groups'] = 64
    kwargs['width_per_group'] = 4
    return _resnet(Bottleneck, [3, 4, 23, 3], pretrained, pth_url, **kwargs)


def wide_resnet50_2(pth_url, pretrained=False, **kwargs):
    kwargs['width_per_group'] = 64 * 2
    return _resnet(Bottleneck, [3, 4, 6, 3], pretrained, pth_url, **kwargs)


def wide_resnet101_2(pth_url, pretrained=False, **kwargs):
    kwargs['width_per_group'] = 64 * 2
    return _resnet(Bottleneck, [3, 4, 23, 3], pretrained, pth_url, **kwargs)
