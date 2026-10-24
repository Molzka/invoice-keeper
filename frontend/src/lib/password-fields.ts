export type PasswordField = 'current_password' | 'new_password' | 'confirm_password'
export type PasswordFields = Record<PasswordField, string>
export type PasswordErrors = Partial<Record<PasswordField, string>>

/** Match the server's Unicode character limits without changing password bytes. */
export function validatePasswordFields(values: PasswordFields): PasswordErrors {
  const errors: PasswordErrors = {}
  const currentLength = Array.from(values.current_password).length
  const newLength = Array.from(values.new_password).length
  if (!currentLength) errors.current_password = 'Введите текущий пароль.'
  else if (currentLength > 128) errors.current_password = 'Не больше 128 символов.'
  if (newLength < 8 || newLength > 128) errors.new_password = 'Новый пароль должен содержать от 8 до 128 символов.'
  else if (values.new_password === values.current_password) errors.new_password = 'Новый пароль должен отличаться от текущего.'
  if (!values.confirm_password) errors.confirm_password = 'Повторите новый пароль.'
  else if (values.confirm_password !== values.new_password) errors.confirm_password = 'Пароли не совпадают.'
  return errors
}
