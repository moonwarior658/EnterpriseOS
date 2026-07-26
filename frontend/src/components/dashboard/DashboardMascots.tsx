const MASCOT_ASSETS: readonly string[] = []

function DashboardMascots() {
  if (MASCOT_ASSETS.length !== 3) {
    return null
  }

  return (
    <div className="dashboard-mascots" aria-hidden="true">
      {MASCOT_ASSETS.map((asset) => (
        <img alt="" key={asset} src={asset} />
      ))}
    </div>
  )
}

export default DashboardMascots
