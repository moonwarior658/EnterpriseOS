export const passwordInputType = (visible: boolean): 'text' | 'password' => (
  visible ? 'text' : 'password'
)

export const passwordToggleLabel = (visible: boolean): string => (
  visible ? 'Скрыть пароль' : 'Показать пароль'
)

export async function copyGeneratedPassword(
  password: string,
  clipboard: Pick<Clipboard, 'writeText'> = navigator.clipboard,
): Promise<void> {
  await clipboard.writeText(password)
}
