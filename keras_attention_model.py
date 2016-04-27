from __future__ import print_function

##############
# Make model #
##############
import os

from keras.engine import Merge
from keras.layers import Lambda, MaxPooling1D, Dense, Flatten, Dropout, Masking, Embedding, TimeDistributed, \
    Convolution1D, Permute
from keras.optimizers import SGD

from word_embeddings import Word2VecEmbedding

models_path = 'models/'


def make_model(maxlen_question, maxlen_answer, n_words, n_lstm_dims=141, n_embed_dims=128):
    from keras.optimizers import RMSprop

    from attention_lstm import AttentionLSTM

    from keras.layers import Input, LSTM, merge
    from keras.models import Model
    import keras.backend as K

    # input
    question = Input(shape=(maxlen_question,), dtype='int32', name='question_input')
    answer_good = Input(shape=(maxlen_answer,), dtype='int32', name='answer_good_input')
    answer_bad = Input(shape=(maxlen_answer,), dtype='int32', name='answer_bad_input')

    # language model
    embedding = Embedding(n_words, n_embed_dims)

    # forward and backward lstms
    f_lstm = LSTM(n_lstm_dims, name='fq_lstm', consume_less='mem', return_sequences=True)
    b_lstm = LSTM(n_lstm_dims, name='bq_lstm', go_backwards=True, consume_less='mem', return_sequences=True)
    f_lstm_2 = LSTM(n_lstm_dims, consume_less='mem', return_sequences=False)
    b_lstm_2 = LSTM(n_lstm_dims, go_backwards=True, consume_less='mem', return_sequences=False)

    # question part
    q_emb = embedding(question)
    q_emb = Dropout(0.25)(q_emb)
    q_emb = Convolution1D(nb_filter=64, filter_length=5)(q_emb)
    q_emb = MaxPooling1D(pool_length=2)(q_emb)
    q_fl = f_lstm(q_emb)
    q_bl = b_lstm(q_emb)
    q_out = merge([q_fl, q_bl], mode='concat', concat_axis=-1)
    q_fl = f_lstm_2(q_out)
    q_bl = b_lstm_2(q_out)
    q_out = merge([q_fl, q_bl], mode='concat', concat_axis=-1)
    # q_out = Permute((2, 1))(q_out)
    # q_out = Convolution1D(nb_filter=64, filter_length=5)(q_out)
    # q_out = MaxPooling1D(2)(q_out)
    # q_out = Flatten()(q_out)

    # forward and backward attention lstms (paying attention to q_out)
    f_lstm_attention = AttentionLSTM(n_lstm_dims, q_out, consume_less='mem', return_sequences=True)
    b_lstm_attention = AttentionLSTM(n_lstm_dims, q_out, go_backwards=True, consume_less='mem', return_sequences=True)
    f_lstm_attention_2 = AttentionLSTM(n_lstm_dims, q_out, consume_less='mem', return_sequences=False)
    b_lstm_attention_2 = AttentionLSTM(n_lstm_dims, q_out, go_backwards=True, consume_less='mem', return_sequences=False)

    conv = Convolution1D(nb_filter=64, filter_length=5)

    # answer part
    ag_emb = embedding(answer_good)
    ag_emb = Dropout(0.25)(ag_emb)
    ag_emb = conv(ag_emb)
    ag_emb = MaxPooling1D(pool_length=2)(ag_emb)
    ag_fl = f_lstm_attention(ag_emb)
    ag_bl = b_lstm_attention(ag_emb)
    ag_out = merge([ag_fl, ag_bl], mode='concat', concat_axis=-1)
    ag_fl = f_lstm_attention_2(ag_out)
    ag_bl = b_lstm_attention_2(ag_out)
    ag_out = merge([ag_fl, ag_bl], mode='concat', concat_axis=-1)
    # ag_out = Permute((2, 1))(ag_out)
    # ag_out = conv(ag_out)
    # ag_out = MaxPooling1D(2)(ag_out)
    # ag_out = Flatten()(ag_out)

    ab_emb = embedding(answer_bad)
    ab_emb = Dropout(0.25)(ab_emb)
    ab_emb = conv(ab_emb)
    ab_emb = MaxPooling1D(pool_length=2)(ab_emb)
    ab_fl = f_lstm_attention(ab_emb)
    ab_bl = b_lstm_attention(ab_emb)
    ab_out = merge([ab_fl, ab_bl], mode='concat', concat_axis=-1)
    ab_fl = f_lstm_attention_2(ab_out)
    ab_bl = b_lstm_attention_2(ab_out)
    ab_out = merge([ab_fl, ab_bl], mode='concat', concat_axis=-1)
    # ab_out = Permute((2, 1))(ab_out)
    # ab_out = conv(ab_out)
    # ab_out = MaxPooling1D(2)(ab_out)
    # ab_out = Flatten()(ab_out)

    # merge together
    # note: `cos` refers to "cosine similarity", i.e. similar vectors should go to 1
    # for training's sake, "abs" limits range to between 0 and 1 (binary classification)
    good_out = merge([q_out, ag_out], name='good', mode='cos', dot_axes=1)
    bad_out = merge([q_out, ab_out], name='bad', mode='cos', dot_axes=1)

    target = merge([good_out, bad_out], name='target', mode=lambda x: K.maximum(1e-3, 0.2 - x[0] + x[1]), output_shape=lambda x: x[0])

    train_model = Model(input=[question, answer_good, answer_bad], output=target)
    test_model = Model(input=[question, answer_good], output=good_out)

    print('Compiling model...')

    optimizer = RMSprop(lr=0.0001, clipnorm=0.05)
    # optimizer = SGD(lr=1e-3, decay=1e-6, momentum=0.9, nesterov=True, clipgrad=0.1)

    # this is more true to the paper: L = max{0, M - cosine(q, a+) + cosine(q, a-)}
    # below, "a" is a list of zeros and "b" is `target` above, i.e. 1 - cosine(q, a+) + cosine(q, a-)
    # loss = 'binary_crossentropy'
    # loss = 'mse'
    # loss = 'hinge'

    def loss(y_true, y_pred):
        return y_pred

    # unfortunately, the hinge loss approach means the "accuracy" metric isn't very valuable
    metrics = []

    train_model.compile(optimizer=optimizer, loss=loss, metrics=metrics)
    test_model.compile(optimizer=optimizer, loss=loss, metrics=metrics)

    return train_model, test_model

if __name__ == '__main__':
    # get the data set
    maxlen = 40 # words

    from utils.get_data import get_data_set, create_dictionary_from_qas

    dic = create_dictionary_from_qas()
    targets, questions, good_answers, bad_answers, n_dims = get_data_set(maxlen)

    train_model, test_model = make_model(maxlen, n_dims)

    print('Fitting model')
    train_model.fit([questions, good_answers, bad_answers], targets, nb_epoch=5, batch_size=128)
    train_model.save_weights(os.path.join(models_path, 'attention_lm_weights.h5'), overwrite=True)
