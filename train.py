import helper
import re


dir = '全唐诗.txt'
text = helper.load_text(dir)

num_words_for_training = 250000
text = text[:num_words_for_training]
lines_of_text = text[20:]
lines_of_text = lines_of_text.split('\n')




# 将上面的正则换成负责找行中的空格
pattern = re.compile(r' +')

# 将所有指定内容替换成空
lines_of_text = [pattern.sub("", lines) for lines in lines_of_text]

pattern = re.compile(r'卷\d+')
lines_of_text = [lines for lines in lines_of_text if not re.match(pattern,lines)]

pattern = re.compile(r'-+')
lines_of_text = [lines for lines in lines_of_text if not re.match(pattern,lines)]

lines_of_text = [lines for lines in lines_of_text if len(lines) > 4]

print(len(lines_of_text))
print(lines_of_text[:200])

def create_lookup_tables(input_data):
    vocab = set(input_data)
    # 文字到数字的映射
    vocab_to_int = {word: idx for idx, word in enumerate(vocab)}
    # 数字到文字的映射
    int_to_vocab = dict(enumerate(vocab))
    return vocab_to_int, int_to_vocab

def token_lookup():
    symbols = set(['。', '，', '“', '”', '；', '！', '？', '（', '）', '——', '\n'])

    tokens = ["P", "C", "Q", "T", "S", "E", "M", "I", "O", "D", "R"]

    return dict(zip(symbols, tokens))

helper.preprocess_and_save_data(''.join(lines_of_text), token_lookup, create_lookup_tables)
int_text, vocab_to_int, int_to_vocab, token_dict = helper.load_preprocess()

print(int_text)
print(vocab_to_int)
print(int_to_vocab)
print(token_dict)

import tensorflow as tf
import numpy as np

# 训练循环次数
num_epochs = 200
# batch大小
batch_size = 256
# lstm层中包含的unit个数
rnn_size = 1024
# embedding layer的大小
embed_dim = 1024
# 训练步长
seq_length = 30
# 学习率
learning_rate = 0.001
# 每多少步打印一次训练信息
show_every_n_batches = 30
# 保存session状态的位置
save_dir = r'D:\Asset\Data\peotry\model\save'

def get_inputs():

    # inputs和targets的类型都是整数的
    inputs = tf.placeholder(tf.int32, [None, None], name='inputs')
    targets = tf.placeholder(tf.int32, [None, None], name='targets')
    learning_rate = tf.placeholder(tf.float32, name='learning_rate')

    return inputs, targets, learning_rate

def get_init_cell(batch_size, rnn_size):
    # lstm层数
    num_layers = 2

    # dropout时的保留概率
    keep_prob = 0.8

    # 创建包含rnn_size个神经元的lstm cell
    cell = tf.contrib.rnn.BasicLSTMCell(rnn_size)

    # 使用dropout机制防止overfitting等
    drop = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=keep_prob)

    # 创建2层lstm层
    cell = tf.contrib.rnn.MultiRNNCell([drop for _ in range(num_layers)])

    # 初始化状态为0.0
    init_state = cell.zero_state(batch_size, tf.float32)

    # 使用tf.identify给init_state取个名字，后面生成文字的时候，要使用这个名字来找到缓存的state
    init_state = tf.identity(init_state, name='init_state')

    return cell, init_state


def get_embed(input_data, vocab_size, embed_dim):
    # 先根据文字数量和embedding layer的size创建tensorflow variable
    embedding = tf.Variable(tf.truncated_normal([vocab_size, embed_dim], stddev=0.1),
                            dtype=tf.float32, name="embedding")

    # 让tensorflow帮我们创建lookup table
    return tf.nn.embedding_lookup(embedding, input_data, name="embed_data")


def build_rnn(cell, inputs):
    '''
    cell就是上面get_init_cell创建的cell
    '''

    outputs, final_state = tf.nn.dynamic_rnn(cell, inputs, dtype=tf.float32)

    # 同样给final_state一个名字，后面要重新获取缓存
    final_state = tf.identity(final_state, name="final_state")

    return outputs, final_state


def build_nn(cell, rnn_size, input_data, vocab_size, embed_dim):
    # 创建embedding layer
    embed = get_embed(input_data, vocab_size, embed_dim)

    # 计算outputs 和 final_state
    outputs, final_state = build_rnn(cell, embed)

    # 记住初始化权重和偏差，否则损失将停留在非常高的位置
    logits = tf.contrib.layers.fully_connected(outputs, vocab_size, activation_fn=None,
                                               weights_initializer=tf.truncated_normal_initializer(stddev=0.1),
                                               biases_initializer=tf.zeros_initializer())

    # logits = tf.contrib.layers.fully_connected(outputs, vocab_size, activation_fn=None)

    return logits, final_state


def get_batches(int_text, batch_size, seq_length):

    # 计算有多少个batch可以创建
    characters_per_batch = batch_size * seq_length
    num_batches = len(int_text) // characters_per_batch

    # 计算每一步的原始数据，和位移一位之后的数据
    input_data = np.array(int_text[: num_batches * characters_per_batch])
    target_data = np.array(int_text[1: num_batches * characters_per_batch + 1])

    inputs = input_data.reshape(batch_size, -1)
    targets = target_data.reshape(batch_size, -1)

    inputs = np.split(inputs, num_batches, 1)
    targets = np.split(targets, num_batches, 1)

    # 将位移之后的数据的最后一位，设置成原始数据的第一位，相当于在做循环
    batches = np.array(list(zip(inputs, targets)))
    batches[-1][-1][-1][-1] = batches[0][0][0][0]

    return batches

# 导入seq2seq，下面会用他计算loss
from tensorflow.contrib import seq2seq

train_graph = tf.Graph()
with train_graph.as_default():
    # 文字总量
    vocab_size = len(int_to_vocab)
    print(vocab_size)
    # 获取模型的输入，目标以及学习率节点，这些都是tf的placeholder
    input_text, targets, lr = get_inputs()

    # 输入数据的shape
    input_data_shape = tf.shape(input_text)

    # 创建rnn的cell和初始状态节点，rnn的cell已经包含了lstm，dropout
    # 这里的rnn_size表示每个lstm cell中包含了多少的神经元
    cell, initial_state = get_init_cell(input_data_shape[0], rnn_size)

    # 创建计算loss和finalstate的节点
    logits, final_state = build_nn(cell, rnn_size, input_text, vocab_size, embed_dim)

    # 使用softmax计算最后的预测概率
    probs = tf.nn.softmax(logits, name='probs')

    # 计算loss
    cost = seq2seq.sequence_loss(
        logits,
        targets,
        tf.ones([input_data_shape[0], input_data_shape[1]]))

    # 使用Adam梯度下降
    optimizer = tf.train.AdamOptimizer(lr)

    # 裁剪一下Gradient输出，最后的gradient都在[-1, 1]的范围内
    gradients = optimizer.compute_gradients(cost)
    capped_gradients = [(tf.clip_by_value(grad, -1., 1.), var) for grad, var in gradients if grad is not None]
    train_op = optimizer.apply_gradients(capped_gradients)

    # 获得训练用的所有batch
    batches = get_batches(int_text, batch_size, seq_length)

    # 打开session开始训练，将上面创建的graph对象传递给session
    with tf.Session(graph=train_graph) as sess:
        sess.run(tf.global_variables_initializer())

        for epoch_i in range(num_epochs):
            state = sess.run(initial_state, {input_text: batches[0][0]})

            for batch_i, (x, y) in enumerate(batches):
                feed = {
                    input_text: x,
                    targets: y,
                    initial_state: state,
                    lr: learning_rate}
                train_loss, state, _ = sess.run([cost, final_state, train_op], feed)

                # 打印训练信息
                if (epoch_i * len(batches) + batch_i) % show_every_n_batches == 0:
                    print('Epoch {:>3} Batch {:>4}/{}   train_loss = {:.3f}'.format(
                        epoch_i,
                        batch_i,
                        len(batches),
                        train_loss))

        # 保存模型
        saver = tf.train.Saver()
        saver.save(sess, save_dir)

        helper.save_params((seq_length, save_dir))
        print('Model Trained and Saved')



