"""Trains the 'holding a weight / empty hand' classifier on the crops from tools/hand_crops.py.
Runs in its own environment with PyTorch (~/cnn_env), not in fitform_env:
  ~/cnn_env/bin/python tools/train_hand_classifier.py --train 1 --test 2     # train on round 1, test on round 2
  ~/cnn_env/bin/python tools/train_hand_classifier.py --train 1              # no round 2 yet: test on the last
                                                                             # quarter of every round-1 clip
Model: MobileNetV3-Small pretrained on ImageNet, last layer replaced by 2 outputs, all layers fine-tuned.
Output: models/hand_holding.onnx (run in FitForm through OpenCV's DNN module - no PyTorch needed there)
and models/hand_holding_report.txt (accuracy per camera / per kind of hand, confusion matrix)."""

import argparse
import glob
import os
import random
import re
import time

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CROPS = os.path.join(ROOT, "logs", "hand_crops")
OUT = os.path.join(ROOT, "models")
CLASSES = ["empty", "holding"]
SIZE = 128
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
NAME = re.compile(r"^(?P<clip>[A-Za-z]+\d+)_(?P<cam>front|side)_(?P<arm>right|left)_(?P<frame>\d+)\.jpg$")


def collect(rounds):
    items = []
    for rnd in rounds:
        for ci, cls in enumerate(CLASSES):
            for p in glob.glob(os.path.join(CROPS, rnd, cls, "*.jpg")):
                m = NAME.match(os.path.basename(p))
                if m:
                    items.append((p, ci, m.groupdict()))
    return items


def split_by_time(items, test_share=0.25):
    """Same round for training and testing: the last part of every clip is the test set (neighbouring frames
    are almost identical, so a random split would test on pictures the model has practically seen)."""
    last = {}
    for _, _, g in items:
        last[g["clip"]] = max(last.get(g["clip"], 0), int(g["frame"]))
    train, test = [], []
    for it in items:
        g = it[2]
        (test if int(g["frame"]) > (1 - test_share) * last[g["clip"]] else train).append(it)
    return train, test


class Crops(Dataset):
    def __init__(self, items, tf):
        self.items, self.tf = items, tf

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p, y, _ = self.items[i]
        return self.tf(Image.open(p).convert("RGB")), y


def kind(g):
    c = g["clip"].rstrip("0123456789")
    if c.startswith("bottle"):
        holding_arm = "left" if c == "bottleL" else "right"
        return "bottle" if g["arm"] == holding_arm else "empty (other hand)"
    return f"empty {c}"


def evaluate(model, items, tf):
    model.eval()
    preds = []
    with torch.no_grad():
        for x, _ in DataLoader(Crops(items, tf), batch_size=128):
            preds += model(x).argmax(1).tolist()
    return preds


def report(items, preds):
    lines = []
    ys = [y for _, y, _ in items]
    acc = np.mean([p == y for p, y in zip(preds, ys)]) if ys else 0
    lines.append(f"Overall accuracy: {100 * acc:.1f} % ({len(ys)} test pictures)")
    cm = np.zeros((2, 2), int)
    for p, y in zip(preds, ys):
        cm[y, p] += 1
    lines.append("Confusion matrix (rows = truth, columns = predicted):")
    lines.append(f"{'':>10}{'empty':>9}{'holding':>9}")
    for i, c in enumerate(CLASSES):
        lines.append(f"{c:>10}{cm[i, 0]:>9}{cm[i, 1]:>9}")
    for title, key in (("By camera", lambda g: g["cam"]), ("By kind of hand", kind)):
        lines.append(title + ":")
        groups = {}
        for (_, y, g), p in zip(items, preds):
            groups.setdefault(key(g), []).append(p == y)
        for k in sorted(groups):
            lines.append(f"  {k:<22} {100 * np.mean(groups[k]):5.1f} %  ({len(groups[k])})")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", nargs="+", default=["1"], help="rounds to train on")
    ap.add_argument("--test", nargs="*", default=[], help="rounds to test on (default: time split of --train)")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--all", action="store_true", help="final model: train on every picture, no test set "
                    "(report the accuracy from an earlier run with --test)")
    args = ap.parse_args()
    random.seed(0)
    torch.manual_seed(0)
    torch.set_num_threads(os.cpu_count() or 4)

    items = collect(args.train)
    if args.all:
        train, test = items, []
        how = f"final model: trained on every picture of round(s) {' '.join(args.train)} (no test set)"
    elif args.test:
        train, test = items, collect(args.test)
        how = f"trained on round(s) {' '.join(args.train)}, tested on round(s) {' '.join(args.test)}"
    else:
        train, test = split_by_time(items)
        how = f"round(s) {' '.join(args.train)}: first 75 % of every clip for training, last 25 % for testing"
    counts = [sum(1 for _, y, _ in train if y == i) for i in range(2)]
    print(f"{how}\ntrain: {len(train)} ({dict(zip(CLASSES, counts))}), test: {len(test)}")

    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(SIZE, scale=(0.75, 1.0), ratio=(0.85, 1.18)),
        transforms.RandomHorizontalFlip(),                  # a left hand mirrored looks like a right hand
        transforms.RandomRotation(15),
        transforms.ColorJitter(0.35, 0.35, 0.3, 0.03),       # other light / clothes
        transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    test_tf = transforms.Compose([transforms.Resize((SIZE, SIZE)), transforms.ToTensor(),
                                  transforms.Normalize(MEAN, STD)])

    model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, 2)
    weights = torch.tensor([sum(counts) / (2 * max(c, 1)) for c in counts], dtype=torch.float)
    loss_fn = nn.CrossEntropyLoss(weight=weights)           # fewer 'holding' pictures: weigh them up
    opt = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    loader = DataLoader(Crops(train, train_tf), batch_size=64, shuffle=True, num_workers=3)

    for ep in range(args.epochs):
        model.train()
        t0, total, correct, n = time.time(), 0.0, 0, 0
        for x, y in loader:
            opt.zero_grad()
            out = model(x)
            loss = loss_fn(out, y)
            loss.backward()
            opt.step()
            total += loss.item() * len(y)
            correct += (out.argmax(1) == y).sum().item()
            n += len(y)
        sched.step()
        msg = f"epoch {ep + 1}/{args.epochs}: loss {total / n:.3f}, train acc {100 * correct / n:.1f} %"
        if test:
            p = evaluate(model, test, test_tf)
            msg += f", test acc {100 * np.mean([a == b for a, (_, b, _) in zip(p, test)]):.1f} %"
        print(f"{msg}  ({time.time() - t0:.0f} s)", flush=True)

    os.makedirs(OUT, exist_ok=True)
    text = how + "\n" + report(test, evaluate(model, test, test_tf)) if test else how
    with open(os.path.join(OUT, "hand_holding_report.txt"), "w") as f:
        f.write(text + "\n")
    print(text)
    model.eval()
    onnx_path = os.path.join(OUT, "hand_holding.onnx")
    torch.onnx.export(model, torch.zeros(1, 3, SIZE, SIZE), onnx_path, input_names=["image"],
                      output_names=["logits"], opset_version=17, dynamo=False)
    print(f"saved {onnx_path} ({os.path.getsize(onnx_path) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
