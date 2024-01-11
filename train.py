import pandas as pd
import numpy as np
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from matplotlib import pyplot as plt
from model import Net, classes
from config import feature_filter, batch_size, split_ratio, epochs, device, data_folder
import flask
from flask import request
from io import StringIO
import json
import pandas as pd
from config import feature_filter, device
import logging
import sys

data = []
labels = []

for class_folder in os.listdir(data_folder):
    class_folder_path = os.path.join(data_folder, class_folder)
    if not os.path.isdir(class_folder_path):
        continue
    class_label = classes[class_folder]
    for csv_file in os.listdir(class_folder_path):
        if csv_file.endswith('.csv'):
            csv_file_path = os.path.join(class_folder_path, csv_file)
            df = pd.read_csv(csv_file_path, sep=';', skiprows=1)
            df = df.iloc[:, :-1]
            df = df.iloc[:, feature_filter[0]:feature_filter[1]]
            df = (df-df.min())/(df.max()-df.min())
            data_array = df.to_numpy()
            result_array = np.zeros((100, 3))
            result_array[:data_array.shape[0], :] = data_array
            data.append(result_array)
            labels.append(class_label)

data = np.array(data)
labels = np.array(labels)

permutation = np.random.permutation(len(data))
data = data[permutation]
labels = labels[permutation]

split_index = int(len(data) * split_ratio)
x_train, x_test = data[:split_index], data[split_index:]
y_train, y_test = labels[:split_index], labels[split_index:]

train_loader = torch.utils.data.DataLoader(torch.utils.data.TensorDataset(
    torch.Tensor(x_train), torch.Tensor(y_train)), batch_size=batch_size, shuffle=True)
test_loader = torch.utils.data.DataLoader(torch.utils.data.TensorDataset(
    torch.Tensor(x_test), torch.Tensor(y_test)), batch_size=batch_size, shuffle=True)


model = Net(data.shape[2]).to(device)
print(f'Number of features: {data.shape[2]}')
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

training_loss = []
validation_loss = []

validation_acc = []


class EarlyStopper:
    def __init__(self, patience=1, min_delta=0):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.min_validation_loss = float('inf')

    def early_stop(self, validation_loss):
        if validation_loss < self.min_validation_loss:
            self.min_validation_loss = validation_loss
            self.counter = 0
        elif validation_loss > (self.min_validation_loss + self.min_delta):
            self.counter += 1
            if self.counter >= self.patience:
                return True
        return False


early_stopper = EarlyStopper(patience=3, min_delta=10)
for epoch in range(epochs):
    step_loss = []
    for batch_idx, (x, y) in enumerate(train_loader):
        model.train()
        x = x.to(device)
        y = y.to(device)
        optimizer.zero_grad()
        output = model(x)
        y = F.one_hot(y.long(), len(classes.keys())).float()
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()
        step_loss.append(loss.item())
        validation_step_loss = []
        if early_stopper.early_stop(loss):
            break
        if batch_idx % 100 == 0:
            model.eval()

            num_correct = 0
            num_samples = 0

            with torch.no_grad():
                for x, y in test_loader:
                    x = x.to(device)
                    y = y.to(device)
                    output = model(x)
                    _, predicted = torch.max(output.data, 1)
                    num_samples += y.size(0)
                    num_correct += (predicted == y).sum().item()
                    y = F.one_hot(y.long(), len(classes.keys())).float()
                    validation_step_loss.append(criterion(output, y))

            accuracy = num_correct / num_samples
            validation_acc.append(accuracy)
            print(
                f'Epoch {epoch+1}, Batch {batch_idx}, Loss {loss.item()}, Accuracy {accuracy}')
            validation_loss.append(np.array(validation_step_loss).mean())
    training_loss.append(np.array(step_loss).mean())

torch.save(model.state_dict(), 'model.pt')

plt.title('Loss')
plt.plot(training_loss, label='train_loss')
plt.plot(validation_loss, label='val_loss')
plt.legend()
plt.savefig('loss.png')

plt.clf()

plt.title('Accuracy')
plt.plot(validation_acc, label='val_acc')
plt.legend()
plt.savefig('acc.png')


model = Net(3).to(device)
model.load_state_dict(torch.load('model.pt'))
model.eval()

app = flask.Flask(__name__)


@app.route('/inference', methods=['POST'])
def interference():
    d = request.data.decode('utf-8')
    print(d)
    df = pd.read_csv(StringIO(d), sep=';', skiprows=1)
    df = df.iloc[:, :-1]
    df = df.iloc[:, feature_filter[0]:feature_filter[1]]
    df = (df-df.min())/(df.max()-df.min())
    data_array = df.to_numpy()
    result_array = np.zeros((100, 3))
    result_array[:data_array.shape[0], :] = data_array
    data = torch.Tensor(result_array).unsqueeze(0).to(device)
    output = model(data)
    output = output.cpu().detach().numpy()
    print(output)
    return json.dumps(output.tolist())


cli = sys.modules['flask.cli']
cli.show_server_banner = lambda *x: None
log = logging.getLogger('werkzeug')
log.disabled = True
print('Inference server listening...')
app.run(host='0.0.0.0', port=4199)
