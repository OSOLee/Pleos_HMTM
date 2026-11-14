"""신호등 색 분류 모델 (작은 CNN, CPU로 몇 분이면 학습)

HSV 규칙(light_color.py)은 켜진 등 가운데가 하얗게 날아가거나 주변 간판·하늘 색에 흔들려서 학습 세트에서도
66%가 한계였다. 그래서 잘라 낸 신호등 그림(src/dataset/light_crops.py)으로 작은 CNN을 학습한다.

  python src/analyze/light_cnn.py train outputs/lights     # → models/light_cnn.pt
  python src/analyze/light_cnn.py eval outputs/lights      # 검증·시험 정확도

라벨은 AI Hub 그대로 red / green / etc(노랑·꺼짐·화살표 등). 노랑은 따로 라벨이 없어서 etc 안에 섞여 있다.
"""
import json
import os
import random
import sys
from collections import Counter

import cv2
import numpy as np
import torch
from torch import nn

CLASSES = ["red", "green", "etc"]
SIZE = (32, 64)     # (폭, 높이). 신호등은 대부분 가로로 긴 한국식이지만 세로형도 있어서 그대로 늘려 맞춤
MODEL = "models/light_cnn.pt"
EPOCHS = 8
SEED = 0


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        def block(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(), nn.MaxPool2d(2))
        self.f = nn.Sequential(block(3, 16), block(16, 32), block(32, 64), nn.AdaptiveAvgPool2d(1))
        self.h = nn.Linear(64, len(CLASSES))

    def forward(self, x):
        return self.h(self.f(x).flatten(1))


def prep(img):
    """BGR 그림 → (3, 64, 32) 0~1 텐서. 가로로 긴 신호등은 세워서 모양을 맞춤"""
    if img.shape[1] > img.shape[0]:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    img = cv2.resize(img, SIZE, interpolation=cv2.INTER_AREA)
    return torch.from_numpy(img[..., ::-1].copy()).permute(2, 0, 1).float() / 255


def load(data_dir, split):
    rows = [r for r in json.load(open(os.path.join(data_dir, "index.json"), encoding="utf-8")) if r["split"] == split]
    x = torch.stack([prep(cv2.imread(os.path.join(data_dir, "crops", r["file"]))) for r in rows])
    y = torch.tensor([CLASSES.index(r["label"]) for r in rows])
    return x, y


def train(data_dir):
    torch.manual_seed(SEED); random.seed(SEED)
    x, y = load(data_dir, "train")
    xv, yv = load(data_dir, "val")
    net = Net()
    w = torch.tensor([len(y) / (len(CLASSES) * max(1, int((y == k).sum()))) for k in range(len(CLASSES))])
    loss_fn = nn.CrossEntropyLoss(weight=w)   # 초록이 많아서 클래스 비율로 보정
    opt = torch.optim.Adam(net.parameters(), 1e-3)
    best = 0
    for ep in range(EPOCHS):
        net.train()
        for i in torch.randperm(len(x)).split(128):
            xb = x[i]
            xb = xb * (0.7 + 0.6 * torch.rand(len(xb), 1, 1, 1))     # 밝기 흔들기 (낮·밤, 노출)
            opt.zero_grad(); loss_fn(net(xb.clamp(0, 1)), y[i]).backward(); opt.step()
        acc = (predict_tensor(net, xv) == yv).float().mean().item()
        print(f"epoch {ep + 1}: 검증 정확도 {acc:.3f}")
        if acc > best:
            best = acc
            os.makedirs(os.path.dirname(MODEL), exist_ok=True)
            torch.save(net.state_dict(), MODEL)
    print(f"저장: {MODEL} (검증 {best:.3f})")


def predict_tensor(net, x):
    net.eval()
    with torch.no_grad():
        return torch.cat([net(b).argmax(1) for b in x.split(512)])


_net = None


def classify(img):
    """BGR 그림 → (색, 확률). 색은 red / green / etc. 모델이 없으면 None"""
    global _net
    if _net is None:
        if not os.path.exists(MODEL):
            return None, 0.0
        _net = Net(); _net.load_state_dict(torch.load(MODEL)); _net.eval()
    with torch.no_grad():
        p = torch.softmax(_net(prep(img)[None]), 1)[0]
    k = int(p.argmax())
    return CLASSES[k], round(float(p[k]), 3)


def evaluate(data_dir):
    net = Net(); net.load_state_dict(torch.load(MODEL))
    for sp in ("val", "test"):
        x, y = load(data_dir, sp)
        pr = predict_tensor(net, x)
        conf = Counter(zip(y.tolist(), pr.tolist()))
        print(f"[{sp}] {len(y)}개, 정확도 {(pr == y).float().mean().item():.3f}")
        for a, ca in enumerate(CLASSES):
            tot = int((y == a).sum())
            print(f"  정답 {ca:5} {tot:5}개 →", {cb: conf[(a, b)] for b, cb in enumerate(CLASSES)},
                  f"재현율 {conf[(a, a)] / max(tot, 1):.3f}")


if __name__ == "__main__":
    {"train": train, "eval": evaluate}[sys.argv[1]](sys.argv[2] if len(sys.argv) > 2 else "outputs/lights")
