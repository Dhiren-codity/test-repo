# frozen_string_literal: true

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    it 'returns healthy statuses for all services' do
      allow(HTTParty).to receive(:get).and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']).to include('ruby', 'go', 'python')
      expect(body['services']['ruby']['status']).to eq('healthy')
      expect(body['services']['go']['status']).to eq('healthy')
      expect(body['services']['python']['status']).to eq('healthy')
    end

    it 'returns unreachable when dependent services are down' do
      allow(HTTParty).to receive(:get).and_raise(StandardError.new('timeout'))

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']['go']['status']).to eq('unreachable')
      expect(body['services']['python']['status']).to eq('unreachable')
      expect(body['services']['go']).to have_key('error')
      expect(body['services']['python']).to have_key('error')
    end
  end

  describe 'POST /analyze validations and behavior' do
    it 'returns 422 when validation fails' do
      validation_errors = [double(to_hash: { field: 'content', message: 'is required' })]
      allow(RequestValidator).to receive(:validate_analyze_request).and_return(validation_errors)

      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to eq([{ 'field' => 'content', 'message' => 'is required' }])
    end

    it 'falls back to params when JSON is invalid' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |v| v }
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'print("x")', path: 'main.py'), anything)
        .and_return({ 'language' => 'python', 'lines' => ['print("x")'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'print("x")', language: 'python'), anything)
        .and_return({ 'score' => 90, 'issues' => [] })

      # Send invalid JSON; params should be used
      post '/analyze', 'not-json',
           { 'CONTENT_TYPE' => 'application/json', 'QUERY_STRING' => 'content=print("x")&path=main.py' }
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['summary']).to include('language', 'lines', 'review_score', 'issues_count')
    end

    it 'detects language from path and passes it to python service' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |v| v }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts "hi"'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts "hi"'), anything)
        .and_return({ 'score' => 75, 'issues' => [] })

      post '/analyze', { content: 'puts "hi"', path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content is missing' do
      post '/diff', { new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to match(/Missing old_content or new_content/)
    end

    it 'returns 400 when new_content is missing' do
      post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to match(/Missing old_content or new_content/)
    end

    it 'calls services and returns diff and review' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return({ 'changes' => 1 })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'))
        .and_return({ 'score' => 80 })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to eq({ 'changes' => 1 })
      expect(body['new_code_review']).to eq({ 'score' => 80 })
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing content')
    end

    it 'returns metrics, review and computed overall_quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code'))
        .and_return({ 'complexity' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code'))
        .and_return({ 'score' => 90, 'issues' => [{}] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']).to eq({ 'complexity' => 1 })
      expect(body['review']).to eq({ 'score' => 90, 'issues' => [{}] })
      expect(body['overall_quality']).to eq(30.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files are missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing files array')
    end

    it 'returns computed dashboard summary with health score' do
      allow(Time).to receive(:now).and_return(double(iso8601: '2025-01-01T00:00:00Z'))

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: array_including({ 'path' => 'a.rb' })))
        .and_return({ 'total_files' => 2, 'total_lines' => 100, 'languages' => { 'ruby' => 1 } })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: array_including({ 'path' => 'a.rb' })))
        .and_return({ 'average_score' => 80, 'total_issues' => 4, 'average_complexity' => 0.5 })

      post '/dashboard', { files: [{ path: 'a.rb', content: 'puts' }, { path: 'b.py', content: 'print' }] }.to_json,
           'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['timestamp']).to eq('2025-01-01T00:00:00Z')
      expect(body['file_statistics']).to include('total_files' => 2, 'total_lines' => 100)
      expect(body['review_statistics']).to include('average_score' => 80, 'total_issues' => 4)
      expect(body['summary']).to include(
        'total_files' => 2,
        'total_lines' => 100,
        'average_quality_score' => 80,
        'total_issues' => 4
      )
      expect(body['summary']['health_score']).to eq(61.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with count' do
      traces = [{ 'id' => 'c1', 'path' => '/analyze' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(1)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns traces for a given correlation id' do
      traces = [{ 'step' => 'start' }, { 'step' => 'end' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return(traces)

      get '/traces/abc'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq('abc')
      expect(body['trace_count']).to eq(2)
      expect(body['traces']).to eq(traces)
    end

    it 'returns 404 when no traces are found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('none').and_return([])

      get '/traces/none'
      expect(last_response.status).to eq(404)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('No traces found for correlation ID')
    end
  end

  describe 'Validation errors management' do
    it 'GET /validation/errors returns list and count' do
      errors = [{ field: 'content', message: 'bad' }, { field: 'path', message: 'missing' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_errors']).to eq(2)
      expect(body['errors']).to eq([{ 'field' => 'content', 'message' => 'bad' },
                                    { 'field' => 'path', 'message' => 'missing' }])
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors).and_return(nil)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end
end
