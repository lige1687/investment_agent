import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Alert, Button } from 'antd'

interface Props {
  children: ReactNode
  onReload?: () => void
}

interface State {
  failed: boolean
}

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    console.error('A frontend module failed and was isolated by the error boundary')
  }

  private reload = () => {
    if (this.props.onReload) {
      this.props.onReload()
      return
    }
    window.location.reload()
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <Alert
        type="error"
        showIcon
        message="页面模块出现异常"
        description="已隔离异常内容，未展示请求详情。请重新加载后再试。"
        action={<Button aria-label="重新加载" onClick={this.reload}>重新加载</Button>}
      />
    )
  }
}

