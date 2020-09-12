import os
# 读取 label.csv
import pandas as pd
# 读取图片
from PIL import Image
import numpy as np

import torch
# Loss function
import torch.nn.functional as F
# 读取资料
import torchvision.datasets as datasets
from torch.utils.data import Dataset, DataLoader
# 载入预训练的模型
import torchvision.models as models

import torchvision.transforms as transforms
# 显示图片
import matplotlib.pyplot as plt

device = torch.device("cuda")



class Adverdataset(Dataset):
    def __init__(self, root, label, transforms):
        # 图片所在的文件夹
        self.root = root
        # 由 main function 传入的 label
        self.label = torch.from_numpy(label).long()
        # 由 Attacker 传入的 transforms 将载入的图片转换成符合预训练模型的形式
        self.transforms = transforms
        # 图片档案的 list
        self.fnames = []

        for i in range(200):
            self.fnames.append("{:03d}".format(i))

    def __getitem__(self, idx):
        # 利用路径读取图片
        img = Image.open(os.path.join(self.root, self.fnames[idx] + '.png'))
        # 将载入的图片转换成符合预训练模型的形式
        img = self.transforms(img)
        # 图片对应的 label
        label = self.label[idx]
        return img, label

    def __len__(self):
        
        return 200


class Attacker:
    def __init__(self, img_dir, label):
        # 读入预训练模型 vgg16
        self.model = models.vgg16(pretrained=True)
        self.model.cuda()
        self.model.eval()
        self.mean = [0.485, 0.456, 0.406]
        self.std = [0.229, 0.224, 0.225]
        # 把图片 normalize 到 0~1 之间 mean 0 variance 1
        self.normalize = transforms.Normalize(self.mean, self.std, inplace=False)
        transform = transforms.Compose([
            transforms.Resize((224, 224), interpolation=3),
            transforms.ToTensor(),
            self.normalize
        ])
        # 利用 Adverdataset 这个 class 读取资料
        self.dataset = Adverdataset('./data/images', label, transform)

        self.loader = torch.utils.data.DataLoader(
            self.dataset,
            batch_size=1,
            shuffle=False)

    # FGSM 攻击
    def fgsm_attack(self, image, epsilon, data_grad):
        # 找出 gradient 的方向
        sign_data_grad = data_grad.sign()
        # 将图片 gradient 方向乘上 epsilon 的 noise
        perturbed_image = image + epsilon * sign_data_grad
        # 将图片超过 1 或是小于 0 的部分 clip 掉
        # perturbed_image = torch.clamp(perturbed_image, 0, 1)
        return perturbed_image

    def attack(self, epsilon):
        # 存下一些成功攻擊後的圖片 以便之後顯示
        adv_examples = []
        wrong, fail, success = 0, 0, 0
        for (data, target) in self.loader:
            data, target = data.to(device), target.to(device)
            data_raw = data;
            data.requires_grad = True
            # 將圖片丟入 model 進行測試 得出相對應的 class
            output = self.model(data)
            init_pred = output.max(1, keepdim=True)[1]

            # 如果 class 錯誤 就不進行攻擊
            if init_pred.item() != target.item():
                wrong += 1
                continue

            # 如果 class 正確 就開始計算 gradient 進行 FGSM 攻擊
            loss = F.nll_loss(output, target)
            self.model.zero_grad()
            loss.backward()
            data_grad = data.grad.data
            perturbed_data = self.fgsm_attack(data, epsilon, data_grad)

            # 再將加入 noise 的圖片丟入 model 進行測試 得出相對應的 class
            output = self.model(perturbed_data)
            final_pred = output.max(1, keepdim=True)[1]

            if final_pred.item() == target.item():
                # 辨識結果還是正確 攻擊失敗
                fail += 1
            else:
                # 辨識結果失敗 攻擊成功
                success += 1
                # 將攻擊成功的圖片存入
                if len(adv_examples) < 5:
                    adv_ex = perturbed_data * torch.tensor(self.std, device=device).view(3, 1, 1) + torch.tensor(
                        self.mean, device=device).view(3, 1, 1)
                    adv_ex = adv_ex.squeeze().detach().cpu().numpy()
                    data_raw = data_raw * torch.tensor(self.std, device=device).view(3, 1, 1) + torch.tensor(self.mean,
                                                                                                             device=device).view(
                        3, 1, 1)
                    data_raw = data_raw.squeeze().detach().cpu().numpy()
                    adv_examples.append((init_pred.item(), final_pred.item(), data_raw, adv_ex))
        final_acc = (fail / (wrong + success + fail))

        print("Epsilon: {}\tTest Accuracy = {} / {} = {}\n".format(epsilon, fail, len(self.loader), final_acc))
        return adv_examples, final_acc


df = pd.read_csv("./data/labels.csv")
df = df.loc[:, 'TrueLabel'].to_numpy()
label_name = pd.read_csv("./data/categories.csv")
label_name = label_name.loc[:, 'CategoryName'].to_numpy()
# new 一個 Attacker class
attacker = Attacker('./data/images', df)
# 要嘗試的 epsilon
epsilons = [0.5, 0.1, 0.15, 0.20, 0.25, 0.30]

accuracies, examples = [], []

# 進行攻擊 並存起正確率和攻擊成功的圖片
for eps in epsilons:
    ex, acc = attacker.attack(eps)
    accuracies.append(acc)
    examples.append(ex)

cnt = 0
plt.figure(figsize=(30, 30))
for i in range(len(epsilons)):
    for j in range(len(examples[i])):
        cnt += 1
        plt.subplot(len(epsilons),len(examples[0]) * 2,cnt)
        plt.xticks([], [])
        plt.yticks([], [])
        if j == 0:
            plt.ylabel("Eps: {}".format(epsilons[i]), fontsize=14)
        orig,adv,orig_img, ex = examples[i][j]
        # plt.title("{} -> {}".format(orig, adv))
        plt.title("original: {}".format(label_name[orig].split(',')[0]))
        orig_img = np.transpose(orig_img, (1, 2, 0))
        plt.imshow(orig_img)
        cnt += 1
        plt.subplot(len(epsilons),len(examples[0]) * 2,cnt)
        plt.title("adversarial: {}".format(label_name[adv].split(',')[0]))
        ex = np.transpose(ex, (1, 2, 0))
        plt.imshow(ex)
plt.tight_layout()
plt.show()


