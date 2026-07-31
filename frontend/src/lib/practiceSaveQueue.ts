export type SaveAnswer = (questionId: string, answer: string) => Promise<void>;

export interface AnswerSaveQueue {
  enqueue: SaveAnswer;
  flush: (answers: Readonly<Record<string, string>>) => Promise<void>;
}

/**
 * Serializes rapid changes so an older request can never arrive after a newer
 * answer for the same question. `flush` waits for that queue, then persists the
 * latest local snapshot before submission.
 */
export function createAnswerSaveQueue(saveAnswer: SaveAnswer): AnswerSaveQueue {
  let tail = Promise.resolve();

  const append = (operation: () => Promise<void>) => {
    const pending = tail.catch(() => undefined).then(operation);
    tail = pending;
    return pending;
  };

  return {
    enqueue(questionId, answer) {
      return append(() => saveAnswer(questionId, answer));
    },
    flush(answers) {
      return append(async () => {
        for (const [questionId, answer] of Object.entries(answers)) {
          if (answer) await saveAnswer(questionId, answer);
        }
      });
    },
  };
}
